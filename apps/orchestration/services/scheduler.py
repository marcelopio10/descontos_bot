import logging
import random
import time
from dataclasses import dataclass

from apps.curation.services.settings import get_integer_setting
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)


log = logging.getLogger(__name__)

DEFAULT_CYCLE_MIN_MINUTES = 90
DEFAULT_CYCLE_MAX_MINUTES = 180

# Teto/piso de itens por ciclo por canal (Tarefa 1.4 / achado C3, H3): evita
# rajada (muitos itens de uma vez) e evita ciclo "zero" quando há itens
# elegíveis. O piso é só informativo — não força itens inexistentes a existir.
# Teto calibrado contra o volume real observado em produção (canal WhatsApp
# principal, últimos 7 dias): lotes de 15-20 itens são comuns em dias de pico
# (maior lote observado: 20). Um teto de 8 cortaria ~metade dos lotes normais
# e reduziria o volume diário atual — contrário ao objetivo da Sprint 1
# ("parar a sangria de volume"). 25 dá margem sobre o pico observado mantendo
# proteção contra rajada patológica (ex.: centenas de itens após uma queda
# prolongada de canal).
DEFAULT_CHANNEL_ITEMS_MIN_PER_CYCLE = 1
DEFAULT_CHANNEL_ITEMS_MAX_PER_CYCLE = 25


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
    min_items = get_integer_setting(
        'channel_items_min_per_cycle',
        DEFAULT_CHANNEL_ITEMS_MIN_PER_CYCLE,
    )
    max_items = get_integer_setting(
        'channel_items_max_per_cycle',
        DEFAULT_CHANNEL_ITEMS_MAX_PER_CYCLE,
    )

    min_items = max(0, min_items)
    max_items = max(min_items, max_items, 1)

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


def apply_channel_cadence(items: list, config: ChannelCadenceConfig | None = None) -> CadenceApplication:
    """Aplica o teto/piso de cadência do canal (Tarefa 1.4) a uma lista de itens.

    Compartilhado por `run_bot` e `consumir_fila_whatsapp` (achado 2026-07-21):
    qualquer ponto que consuma/envie itens de um lote precisa do mesmo teto,
    senão um consumidor sem essa trava pode drenar um lote inteiro de uma vez
    (rajada) em vez de respeitar o ritmo configurado por ciclo.
    """
    config = config or get_channel_cadence_config()
    total = len(items)
    capped_items = items[: config.max_items_per_cycle]
    return CadenceApplication(
        items=capped_items,
        total=total,
        capped=len(capped_items) < total,
        limit=config.max_items_per_cycle,
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
