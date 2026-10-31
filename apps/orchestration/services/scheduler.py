import logging
import random
import time
from dataclasses import dataclass

from apps.curation.services.settings import (
    get_integer_setting,
    get_positive_integer_setting,
)
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)


log = logging.getLogger(__name__)

DEFAULT_CYCLE_MIN_MINUTES = 90
DEFAULT_CYCLE_MAX_MINUTES = 180
DEFAULT_OFFER_LIMIT_GLOBAL = 20

# Teto/piso de itens por ciclo por canal. O piso é validado aqui e aplicado
# como hard gate pelo montador central do ciclo WhatsApp.
# Teto calibrado contra o volume real observado em produção (canal WhatsApp
# principal, últimos 7 dias): lotes de 15-20 itens são comuns em dias de pico
# (maior lote observado: 20). Um teto de 8 cortaria ~metade dos lotes normais
# e reduziria o volume diário atual. O teto de 20 preserva o maior lote
# observado e mantém proteção contra rajada patológica (por exemplo, centenas
# de itens após uma queda prolongada de canal).
DEFAULT_CHANNEL_ITEMS_MIN_PER_CYCLE = 5
DEFAULT_CHANNEL_ITEMS_MAX_PER_CYCLE = 20


@dataclass(frozen=True)
class SchedulerConfig:
    min_minutes: int
    max_minutes: int


@dataclass(frozen=True)
class ChannelCadenceConfig:
    min_items_per_cycle: int
    max_items_per_cycle: int


def get_scheduler_config() -> SchedulerConfig:
    min_minutes = get_integer_setting(
        'cycle_min_minutes',
        DEFAULT_CYCLE_MIN_MINUTES,
    )
    max_minutes = get_integer_setting(
        'cycle_max_minutes',
        DEFAULT_CYCLE_MAX_MINUTES,
    )

    min_minutes = max(1, min_minutes)
    max_minutes = max(min_minutes, max_minutes)

    return SchedulerConfig(
        min_minutes=min_minutes,
        max_minutes=max_minutes,
    )


def get_channel_cadence_config() -> ChannelCadenceConfig:
    min_items = get_positive_integer_setting(
        'channel_items_min_per_cycle',
        DEFAULT_CHANNEL_ITEMS_MIN_PER_CYCLE,
    )
    max_items = get_positive_integer_setting(
        'channel_items_max_per_cycle',
        DEFAULT_CHANNEL_ITEMS_MAX_PER_CYCLE,
    )
    global_limit = get_positive_integer_setting(
        'offer_limit_global',
        DEFAULT_OFFER_LIMIT_GLOBAL,
    )

    if min_items > max_items:
        raise ValueError(
            'channel_items_min_per_cycle não pode exceder '
            'channel_items_max_per_cycle.',
        )
    if min_items > global_limit:
        raise ValueError(
            'channel_items_min_per_cycle não pode exceder offer_limit_global.',
        )

    return ChannelCadenceConfig(
        min_items_per_cycle=min_items,
        max_items_per_cycle=max_items,
    )


@dataclass(frozen=True)
class CadenceApplication:
    items: list
    total: int
    capped: bool
    limit: int
    below_floor: bool
    floor: int


def apply_channel_cadence(
    items: list,
    config: ChannelCadenceConfig | None = None,
    requested_limit: int | None = None,
) -> CadenceApplication:
    """Aplica o teto/piso de cadência do canal (Tarefa 1.4) a uma lista de itens.

    Compartilhado por `run_bot` e `consumir_fila_whatsapp` (achado 2026-07-21):
    qualquer ponto que consuma/envie itens de um lote precisa do mesmo teto,
    senão um consumidor sem essa trava pode drenar um lote inteiro de uma vez
    (rajada) em vez de respeitar o ritmo configurado por ciclo.
    """
    config = config or get_channel_cadence_config()
    if requested_limit is not None and (
        isinstance(requested_limit, bool)
        or not isinstance(requested_limit, int)
        or requested_limit < 1
    ):
        raise ValueError('requested_limit deve ser um inteiro maior que zero.')
    total = len(items)
    effective_limit = config.max_items_per_cycle
    if requested_limit is not None:
        effective_limit = min(effective_limit, requested_limit)
    capped_items = items[:effective_limit]
    return CadenceApplication(
        items=capped_items,
        total=total,
        capped=len(capped_items) < total,
        limit=effective_limit,
        below_floor=0 < total < config.min_items_per_cycle,
        floor=config.min_items_per_cycle,
    )


def calculate_next_sleep_seconds(config: SchedulerConfig | None = None) -> int:
    config = config or get_scheduler_config()
    return random.randint(config.min_minutes * 60, config.max_minutes * 60)


def sleep_between_cycles(config: SchedulerConfig | None = None) -> int:
    seconds = calculate_next_sleep_seconds(config)
    minutes = seconds / 60
    log.info('Próximo ciclo em %.1f minutos.', minutes)
    time.sleep(seconds)
    return seconds


def wait_until_distribution_window(poll_seconds: int = 60) -> None:
    while is_distribution_silenced():
        log.warning(get_silence_error_message())
        time.sleep(poll_seconds)
