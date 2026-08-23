from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from apps.curation.services.product_family import offer_family_key, product_family_key
from apps.curation.services.settings import get_bool_setting, get_decimal_setting, get_integer_setting
from apps.distribution.models import Delivery

DEFAULT_COOLDOWN_HOURS = 72
DEFAULT_SATURATED_COOLDOWN_HOURS = 120
DEFAULT_RECURRENCE_WINDOW_DAYS = 30
DEFAULT_MAX_FAMILY_SENDS = 2
DEFAULT_MIN_PRICE_DROP = Decimal('0.10')

# Espaçamento por família editorial (achado 2026-08-21). A recorrência acima
# responde "já mandei ESTE produto?"; isto responde "já mandei ALGO DESTE TIPO
# há pouco?". Eram duas piscinas infláveis em 3h e dois power banks em 7h, cada
# par com `produto_canonico_id` diferente — invisíveis para o cooldown antigo.
# Defaults escolhidos com a série real de 7 dias do whatsapp_principal
# (222 envios): 8h de intervalo mínimo e no máximo 2 envios da família por dia
# preservam a cauda longa e cortam só a repetição concentrada.
DEFAULT_FAMILY_COOLDOWN_HOURS = 8
DEFAULT_FAMILY_WINDOW_HOURS = 24
DEFAULT_MAX_FAMILY_WINDOW_SENDS = 2
FAMILY_SPACING_FLAG = 'offer_family_spacing_enabled'
# Teto de linhas lidas do histórico: protege o ciclo de curadoria caso alguém
# aumente muito a janela em Setting.
FAMILY_HISTORY_MAX_ROWS = 1000


@dataclass(frozen=True)
class FamilySpacingSignal:
    family: str
    sends_in_window: int
    last_sent_at: object | None
    blocked: bool
    reason: str


@dataclass(frozen=True)
class RecurrenceSignal:
    family_key: str
    successful_sends: int
    last_sent_at: object | None
    cooldown_until: object | None
    blocked: bool
    penalized: bool
    reason: str


def get_recurrence_config() -> dict[str, object]:
    return {
        'cooldown_hours': max(0, get_integer_setting('offer_recurrence_cooldown_hours', DEFAULT_COOLDOWN_HOURS)),
        'saturated_cooldown_hours': max(0, get_integer_setting('offer_recurrence_saturated_cooldown_hours', DEFAULT_SATURATED_COOLDOWN_HOURS)),
        'window_days': max(1, get_integer_setting('offer_recurrence_window_days', DEFAULT_RECURRENCE_WINDOW_DAYS)),
        'max_family_sends': max(1, get_integer_setting('offer_recurrence_max_family_sends', DEFAULT_MAX_FAMILY_SENDS)),
        'min_price_drop': get_decimal_setting('offer_recurrence_min_price_drop', DEFAULT_MIN_PRICE_DROP),
    }


def normalize_family_key(offer) -> str:
    canonical = (getattr(offer, 'produto_canonico_id', '') or '').strip()
    if canonical:
        return f'canonical:{canonical}'
    text = unicodedata.normalize('NFKD', getattr(offer, 'normalized_title', '') or getattr(offer, 'title', '') or '')
    text = ''.join(char for char in text if not unicodedata.combining(char)).lower()
    tokens = [token for token in re.findall(r'[a-z0-9]+', text) if len(token) >= 3]
    return 'title:' + ' '.join(tokens[:12])


def recurrence_signal(offer, channel, *, now=None, deliveries: QuerySet | None = None) -> RecurrenceSignal:
    now = now or timezone.now()
    config = get_recurrence_config()
    cutoff = now - timedelta(days=int(config['window_days']))
    family = normalize_family_key(offer)
    qs = deliveries if deliveries is not None else Delivery.objects.filter(
        offer__produto_canonico_id=getattr(offer, 'produto_canonico_id', ''),
        social_channel=channel,
        delivery_status=Delivery.DeliveryStatus.SENT,
        sent_at__gte=cutoff,
    )
    if not getattr(offer, 'produto_canonico_id', ''):
        qs = Delivery.objects.filter(
            offer=offer,
            social_channel=channel,
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=cutoff,
        )
    sent_times = list(qs.order_by('-sent_at').values_list('sent_at', flat=True))
    last_sent_at = sent_times[0] if sent_times else None
    saturated = len(sent_times) >= int(config['max_family_sends'])
    cooldown_hours = int(config['saturated_cooldown_hours'] if saturated else config['cooldown_hours'])
    cooldown_until = last_sent_at + timedelta(hours=cooldown_hours) if last_sent_at else None
    blocked = bool(cooldown_until and now < cooldown_until)
    reason = 'cooldown' if blocked else ('recurrence_saturated' if saturated else '')
    return RecurrenceSignal(family, len(sent_times), last_sent_at, cooldown_until, blocked, saturated, reason)


def recurrence_score_multiplier(signal: RecurrenceSignal) -> float:
    if signal.blocked:
        return 0.0
    if signal.penalized:
        return 0.72
    return 1.0


def get_family_spacing_config() -> dict[str, object]:
    return {
        'enabled': get_bool_setting(FAMILY_SPACING_FLAG, True),
        'cooldown_hours': max(0, get_integer_setting('offer_family_cooldown_hours', DEFAULT_FAMILY_COOLDOWN_HOURS)),
        'window_hours': max(1, get_integer_setting('offer_family_window_hours', DEFAULT_FAMILY_WINDOW_HOURS)),
        'max_window_sends': max(1, get_integer_setting('offer_family_max_window_sends', DEFAULT_MAX_FAMILY_WINDOW_SENDS)),
    }


def build_family_history(channel, *, now=None, config: dict[str, object] | None = None) -> dict[str, list]:
    """Mapa família -> horários de envio recentes, lido UMA vez por ciclo.

    Carregar tudo de uma vez e classificar em memória evita N queries por
    candidata e é barato: a janela padrão de 24h tem dezenas de linhas. A
    família não está no banco (é derivada do título), então não dá para
    filtrar por ela no SQL — e não vale uma migração/backfill de coluna só
    para espaçamento, que tolera aproximação.
    """
    now = now or timezone.now()
    config = config or get_family_spacing_config()
    horizon = max(int(config['window_hours']), int(config['cooldown_hours']))
    cutoff = now - timedelta(hours=horizon)
    rows = (
        Delivery.objects
        .filter(
            social_channel=channel,
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=cutoff,
        )
        .order_by('-sent_at')
        .values_list('offer__title', 'offer__normalized_title', 'sent_at')[:FAMILY_HISTORY_MAX_ROWS]
    )
    history: dict[str, list] = {}
    for title, normalized_title, sent_at in rows:
        family = product_family_key(title or '', normalized_title or '')
        if not family or sent_at is None:
            continue
        history.setdefault(family, []).append(sent_at)
    return history


def family_spacing_signal(offer, channel, *, now=None, history: dict[str, list] | None = None, config: dict[str, object] | None = None) -> FamilySpacingSignal:
    now = now or timezone.now()
    config = config or get_family_spacing_config()
    family = offer_family_key(offer)
    if not family:
        # Título do qual não se extrai tipo nenhum: tratar como "sem restrição".
        # O contrário (uma família vazia comum a todos) bloquearia em cadeia
        # ofertas que não têm nada a ver entre si.
        return FamilySpacingSignal('', 0, None, False, '')

    if history is None:
        history = build_family_history(channel, now=now, config=config)
    sent_times = sorted(history.get(family, []), reverse=True)
    last_sent_at = sent_times[0] if sent_times else None

    if not config['enabled']:
        return FamilySpacingSignal(family, len(sent_times), last_sent_at, False, '')

    cooldown_limit = now - timedelta(hours=int(config['cooldown_hours']))
    if last_sent_at is not None and last_sent_at > cooldown_limit:
        return FamilySpacingSignal(family, len(sent_times), last_sent_at, True, 'family_cooldown')

    window_start = now - timedelta(hours=int(config['window_hours']))
    in_window = sum(1 for sent_at in sent_times if sent_at >= window_start)
    if in_window >= int(config['max_window_sends']):
        return FamilySpacingSignal(family, in_window, last_sent_at, True, 'family_window_saturated')

    return FamilySpacingSignal(family, in_window, last_sent_at, False, '')


def filter_saturated_families(offers, channel, *, now=None):
    """Remove candidatas cuja família já saturou a janela recente do canal.

    Roda DEPOIS de `filter_blocked_recurrence`: aquele filtro protege contra
    repetir o mesmo anúncio, este contra repetir o mesmo tipo de produto. O
    histórico considera o que JÁ foi enviado; a diversidade dentro do próprio
    lote é responsabilidade de `batch_optimizer.optimize_curation_batch`.
    """
    config = get_family_spacing_config()
    if not config['enabled']:
        return list(offers)

    now = now or timezone.now()
    history = build_family_history(channel, now=now, config=config)
    kept = []
    for offer in offers:
        signal = family_spacing_signal(offer, channel, now=now, history=history, config=config)
        if signal.blocked:
            continue
        kept.append(offer)
    return kept


def filter_blocked_recurrence(offers, channel):
    """Remove only offers inside cooldown; allow material price improvements."""
    kept = []
    for offer in offers:
        signal = recurrence_signal(offer, channel)
        if signal.blocked:
            from apps.distribution.services.delivery import _should_republish_after_improvement

            previous_delivery = Delivery.objects.filter(
                offer=offer,
                social_channel=channel,
                delivery_status=Delivery.DeliveryStatus.SENT,
            ).order_by('-sent_at').first()
            if previous_delivery is None or not _should_republish_after_improvement(
                previous_delivery,
                offer,
                '',
            ):
                continue
        kept.append(offer)
    return kept
