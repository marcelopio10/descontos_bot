from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity


@dataclass(frozen=True)
class CommercialValidation:
    accepted: bool
    reason: str
    score: float = 0.0


def validate_commercial_candidate(payload: dict[str, Any], opportunity: CommercialOpportunity) -> CommercialValidation:
    title = _normalize(payload.get('title') or payload.get('nome'))
    if not title:
        return CommercialValidation(False, 'missing_title')
    title_tokens = set(title.split())
    brand_tokens = set(opportunity.brand.split())
    if brand_tokens and not brand_tokens.issubset(title_tokens):
        return CommercialValidation(False, 'query_title_mismatch')
    product_terms = set(opportunity.query_text.split()) - set(opportunity.brand.split()) - {'tenis', 'whey', 'perfume', 'fone', 'panela'}
    if product_terms and not any(term in title for term in product_terms):
        return CommercialValidation(False, 'query_title_mismatch')
    url = str(payload.get('product_url') or payload.get('link_direto') or '').strip()
    if not url.startswith(('https://', 'http://')):
        return CommercialValidation(False, 'missing_product_url')
    try:
        price = float(payload.get('current_price') or payload.get('preco') or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return CommercialValidation(False, 'invalid_current_price')
    try:
        original = float(payload.get('original_price') or payload.get('preco_original') or 0)
    except (TypeError, ValueError):
        original = 0
    if original and original <= price:
        return CommercialValidation(False, 'invalid_reference_price')
    rating = float(payload.get('rating') or payload.get('review_rating') or 0)
    sales = int(payload.get('sales') or 0)
    score = min(1.0, (rating / 5) * 0.45 + min(sales / 10000, 1) * 0.35 + (0.2 if original > price else 0))
    return CommercialValidation(True, 'accepted', round(score, 4))


def _normalize(value: Any) -> str:
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').lower()
    return ' '.join(re.findall(r'[a-z0-9]+', text))
