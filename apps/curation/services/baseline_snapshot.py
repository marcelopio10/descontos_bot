from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.curation.services.quality_score import quality_score_breakdown
from apps.curation.services.selector import SelectionConfig, _eligible_offers, get_selection_config
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


def build_baseline_snapshot(
    channel: SocialChannel,
    *,
    config: SelectionConfig | None = None,
    candidate_limit: int | None = None,
) -> dict[str, Any]:
    config = config or get_selection_config()
    limit = candidate_limit or config.global_limit * 5
    candidates = list(_eligible_offers(channel, config).select_related('marketplace', 'category')[:limit])
    offers = [serialize_offer_for_ai(offer) for offer in candidates]
    return {
        'config': {
            'global_limit': config.global_limit,
            'marketplace_limit': config.marketplace_limit,
            'min_discount_percentage': _decimal_to_float(config.min_discount_percentage),
            'min_quality_score': config.min_quality_score,
            'priority_quality_score': config.priority_quality_score,
            'exposure_quota_enabled': config.exposure_quota_enabled,
        },
        'candidate_count': len(offers),
        'quality_score_breakdown': summarize_quality(offers),
        'marketplace_counts': _count_by(offers, 'marketplace_code'),
        'offers': offers,
    }


def serialize_offer_for_ai(offer: Offer) -> dict[str, Any]:
    breakdown = quality_score_breakdown(offer)
    marketplace_code = offer.marketplace.code if offer.marketplace_id else ''
    return {
        'offer_id': offer.id,
        'title': offer.title,
        'marketplace_code': marketplace_code,
        'category_code': offer.category.code if offer.category_id else '',
        'current_price': _decimal_to_float(offer.current_price),
        'original_price': _decimal_to_float(offer.original_price),
        'discount_pct': _decimal_to_float(offer.discount_pct),
        'review_rating': _decimal_to_float(offer.review_rating),
        'review_count': offer.review_count,
        'has_image': bool((offer.image_url or '').strip()),
        'has_bridge_url': bool((offer.slug or '').strip()),
        'baseline': {
            'score': breakdown.as_dict()['score'],
            'classification': breakdown.classification,
            'decision': breakdown.decision,
            'components': breakdown.as_dict()['components'],
            'penalties': breakdown.as_dict()['penalties'],
            'multipliers': breakdown.as_dict()['multipliers'],
            'notes': list(breakdown.notes),
        },
    }


def summarize_quality(offers: list[dict[str, Any]]) -> dict[str, Any]:
    if not offers:
        return {'min': None, 'max': None, 'avg': None, 'classifications': {}}
    scores = [float(offer['baseline']['score']) for offer in offers]
    return {
        'min': round(min(scores), 2),
        'max': round(max(scores), 2),
        'avg': round(sum(scores) / len(scores), 2),
        'classifications': _count_by([offer['baseline'] for offer in offers], 'classification'),
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or 'desconhecido')
        counts[value] = counts.get(value, 0) + 1
    return counts


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
