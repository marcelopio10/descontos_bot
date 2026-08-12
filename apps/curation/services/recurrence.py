from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from apps.curation.services.settings import get_decimal_setting, get_integer_setting
from apps.distribution.models import Delivery

DEFAULT_COOLDOWN_HOURS = 72
DEFAULT_SATURATED_COOLDOWN_HOURS = 120
DEFAULT_RECURRENCE_WINDOW_DAYS = 30
DEFAULT_MAX_FAMILY_SENDS = 2
DEFAULT_MIN_PRICE_DROP = Decimal('0.10')


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


def filter_blocked_recurrence(offers, channel):
    """Remove only offers inside cooldown; keep saturated families for scoring."""
    kept = []
    for offer in offers:
        signal = recurrence_signal(offer, channel)
        if signal.blocked:
            continue
        kept.append(offer)
    return kept
