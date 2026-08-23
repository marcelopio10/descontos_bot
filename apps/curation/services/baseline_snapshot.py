from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from apps.curation.services.product_family import offer_family_key
from apps.curation.services.quality_score import quality_score_breakdown
from apps.curation.services.selector import SelectionConfig, _eligible_offers, get_selection_config
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


def build_baseline_snapshot(
    channel: SocialChannel,
    *,
    config: SelectionConfig | None = None,
    candidate_limit: int | None = None,
    observer_context: dict[str, Any] | None = None,
    market_radar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or get_selection_config()
    limit = candidate_limit or config.global_limit * 5
    candidates = list(_eligible_offers(channel, config).select_related('marketplace', 'category')[:limit])
    offers = [
        serialize_offer_for_ai(offer, observer_context=observer_context, market_radar=market_radar)
        for offer in candidates
    ]
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
        'search_provenance_counts': _count_by_provenance(offers),
        'generic_fallback_count': sum(1 for offer in offers if (offer.get('search_provenance') or {}).get('source_kind') == 'generic_fallback'),
        'offers': offers,
    }


def serialize_offer_for_ai(
    offer: Offer,
    *,
    observer_context: dict[str, Any] | None = None,
    market_radar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    breakdown = quality_score_breakdown(offer, observer_context=observer_context, market_radar=market_radar)
    marketplace_code = offer.marketplace.code if offer.marketplace_id else ''
    editorial_flags = _editorial_flags(offer)
    return {
        'offer_id': offer.id,
        'title': offer.title,
        'marketplace_code': marketplace_code,
        'category_code': offer.category.code if offer.category_id else '',
        # Tipo de produto (achado 2026-08-21): a IA precisa enxergar que duas
        # candidatas são "a mesma coisa" mesmo com títulos diferentes.
        'product_family': offer_family_key(offer),
        'current_price': _decimal_to_float(offer.current_price),
        'original_price': _decimal_to_float(offer.original_price),
        'discount_pct': _decimal_to_float(offer.discount_pct),
        'review_rating': _decimal_to_float(offer.review_rating),
        'review_count': offer.review_count,
        'has_image': bool((offer.image_url or '').strip()),
        'multimodal_image': {
            'available': bool((offer.image_url or '').strip()),
            'source_url_present': bool((offer.image_url or '').strip()),
            'analysis_required_if_selected': True,
            'local_processing_stage': 'post_selection',
        },
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
        'editorial_flags': editorial_flags,
        'search_provenance': _search_provenance(offer),
    }


def _count_by_provenance(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str((row.get('search_provenance') or {}).get('source_kind') or 'unknown')
        counts[source] = counts.get(source, 0) + 1
    return counts


def _search_provenance(offer: Offer) -> dict[str, Any]:
    value = (offer.raw_payload or {}).get('search_provenance')
    return value if isinstance(value, dict) else {}


def _editorial_flags(offer: Offer) -> list[str]:
    flags: list[str] = []
    if _is_low_priority_book(offer):
        flags.append('low_priority_book')
    if _is_low_priority_spinning(offer):
        flags.append('low_priority_spinning')
    if _is_low_priority_generic(offer):
        flags.append('low_priority_generic')
    return flags


def _is_low_priority_book(offer: Offer) -> bool:
    text = ' '.join(
        str(part or '')
        for part in (
            offer.title,
            offer.normalized_title,
            offer.category.code if offer.category_id else '',
            offer.category.name if offer.category_id else '',
            (offer.raw_payload or {}).get('source_label'),
            (offer.raw_payload or {}).get('category_hint'),
        )
    ).lower()
    return bool(
        re.search(r'\b(livro|livros|capa comum|capa dura|kindle|ebook|e-book)\b', text)
    )


def _offer_text(offer: Offer) -> str:
    return ' '.join(
        str(part or '')
        for part in (
            offer.title,
            offer.normalized_title,
            offer.category.code if offer.category_id else '',
            offer.category.name if offer.category_id else '',
            (offer.raw_payload or {}).get('source_label'),
            (offer.raw_payload or {}).get('category_hint'),
        )
    ).lower()


def _is_low_priority_spinning(offer: Offer) -> bool:
    return bool(re.search(r'\b(spinning|bike indoor|bicicleta ergometrica|bicicleta de ciclismo indoor)\b', _offer_text(offer)))


def _is_low_priority_generic(offer: Offer) -> bool:
    text = _offer_text(offer)
    strong_markers = ('nike', 'adidas', 'samsung', 'growth', 'insider', 'lattafa', 'afnan', 'max titanium')
    return not any(term in text for term in strong_markers) and len((offer.title or '').split()) <= 5


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
