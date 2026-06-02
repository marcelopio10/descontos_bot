from dataclasses import dataclass
from decimal import Decimal
from math import log10
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.offers.services.freshness import resolve_max_age_hours


if TYPE_CHECKING:
    from apps.offers.models import Offer


WEIGHT_DISCOUNT = 35.0
WEIGHT_SAVING = 25.0
WEIGHT_IMAGE = 10.0
WEIGHT_TITLE = 10.0
WEIGHT_RECENCY = 10.0
WEIGHT_MARKETPLACE = 10.0

MARKETPLACE_TRUST: dict[str, float] = {
    'amazon': 1.0,
    'mercado_livre': 0.9,
    'mercadolivre': 0.9,
}
DEFAULT_MARKETPLACE_TRUST = 0.7

EXTREME_DISCOUNT_THRESHOLD = Decimal('99')
SUSPECT_DISCOUNT_THRESHOLD = Decimal('85')
PENALTY_NO_IMAGE = 0.7
PENALTY_SUSPECT_PRICE = 0.5
SUSPECT_PRICE_RATIO = Decimal('20')


@dataclass(frozen=True)
class ScoreBreakdown:
    score: float
    components: dict[str, float]
    penalties: dict[str, float]

    def as_dict(self) -> dict:
        return {
            'score': round(self.score, 2),
            'components': {k: round(v, 2) for k, v in self.components.items()},
            'penalties': {k: round(v, 2) for k, v in self.penalties.items()},
        }


def quality_score(offer: 'Offer') -> float:
    return quality_score_breakdown(offer).score


def quality_score_breakdown(offer: 'Offer') -> ScoreBreakdown:
    components = {
        'discount': _score_discount(offer.discount_pct) * WEIGHT_DISCOUNT,
        'saving': _score_saving(offer.absolute_saving) * WEIGHT_SAVING,
        'image': _score_image(offer.image_url) * WEIGHT_IMAGE,
        'title': _score_title(offer.title) * WEIGHT_TITLE,
        'recency': _score_recency(offer.last_seen_at) * WEIGHT_RECENCY,
        'marketplace': _score_marketplace(offer) * WEIGHT_MARKETPLACE,
    }
    base = sum(components.values())

    penalties: dict[str, float] = {}

    if not (offer.image_url or '').strip():
        penalties['no_image'] = PENALTY_NO_IMAGE
    if _has_suspect_original_price(offer):
        penalties['suspect_original_price'] = PENALTY_SUSPECT_PRICE
    if _is_extreme_discount(offer.discount_pct):
        penalties['extreme_discount'] = 0.0

    multiplier = 1.0
    for value in penalties.values():
        multiplier *= value

    final = max(0.0, min(100.0, base * multiplier))
    return ScoreBreakdown(score=final, components=components, penalties=penalties)


def _score_discount(discount_pct: Decimal | None) -> float:
    if discount_pct is None:
        return 0.0

    pct = float(discount_pct)
    if pct <= 0:
        return 0.0
    if pct <= 50:
        return pct / 50.0
    if pct <= float(SUSPECT_DISCOUNT_THRESHOLD):
        return 1.0
    if pct <= float(EXTREME_DISCOUNT_THRESHOLD):
        return max(0.0, 1.0 - (pct - float(SUSPECT_DISCOUNT_THRESHOLD)) / 30.0)
    return 0.0


def _score_saving(absolute_saving: float) -> float:
    if absolute_saving <= 0:
        return 0.0
    if absolute_saving >= 1000:
        return 1.0
    return log10(1 + absolute_saving) / log10(1001)


def _score_image(image_url: str) -> float:
    return 1.0 if (image_url or '').strip() else 0.0


def _score_title(title: str) -> float:
    cleaned = (title or '').strip()
    if not cleaned:
        return 0.0
    if len(cleaned) < 15:
        return 0.4
    if _is_shouty(cleaned):
        return 0.6
    return 1.0


def _is_shouty(title: str) -> bool:
    letters = [ch for ch in title if ch.isalpha()]
    if len(letters) < 10:
        return False
    uppercase = sum(1 for ch in letters if ch.isupper())
    return uppercase / len(letters) > 0.8


def _score_recency(last_seen_at) -> float:
    if last_seen_at is None:
        return 0.0
    max_age_hours = resolve_max_age_hours()
    age_seconds = (timezone.now() - last_seen_at).total_seconds()
    if age_seconds <= 0:
        return 1.0
    age_hours = age_seconds / 3600.0
    if age_hours >= max_age_hours:
        return 0.0
    return 1.0 - (age_hours / max_age_hours)


def _score_marketplace(offer: 'Offer') -> float:
    code = (offer.marketplace.code or '').lower() if offer.marketplace_id else ''
    return MARKETPLACE_TRUST.get(code, DEFAULT_MARKETPLACE_TRUST)


def _has_suspect_original_price(offer: 'Offer') -> bool:
    if offer.original_price is None or offer.current_price is None:
        return False
    if offer.current_price <= 0:
        return False
    ratio = Decimal(offer.original_price) / Decimal(offer.current_price)
    return ratio >= SUSPECT_PRICE_RATIO


def _is_extreme_discount(discount_pct: Decimal | None) -> bool:
    if discount_pct is None:
        return False
    return Decimal(discount_pct) > EXTREME_DISCOUNT_THRESHOLD
