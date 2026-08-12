from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


_ALLOWED_INTENTS = frozenset({'brand_product', 'category_product', 'price_value', 'coupon_signal', 'newness', 'commercial_gap'})
_ALLOWED_SOURCES = frozenset({'radar_brand', 'radar_category', 'radar_price_band', 'radar_coupon_signal', 'priority_catalog'})
_GENERIC = frozenset({'oferta', 'ofertas', 'desconto', 'descontos', 'promocao', 'promoção', 'cupom', 'moda', 'beleza', 'tecnologia', 'casa'})
_BRAND_PRODUCTS = {
    'moda': 'tenis',
    'perfumes_arabes': 'perfume',
    'suplementos': 'whey',
    'tecnologia': 'fone',
    'casa': 'panela',
}
_PRIORITY_BRANDS = (
    ('moda', 'nike'), ('moda', 'adidas'), ('moda', 'mizuno'),
    ('perfumes_arabes', 'lattafa'), ('perfumes_arabes', 'armaf'),
    ('suplementos', 'growth'), ('suplementos', 'dark lab'),
    ('tecnologia', 'samsung'), ('tecnologia', 'jbl'),
    ('casa', 'tramontina'), ('casa', 'electrolux'),
)


@dataclass(frozen=True)
class CommercialOpportunity:
    marketplace: str
    query_text: str
    intent: str
    source_kind: str
    brand: str = ''
    category_code: str = ''
    price_band: str = ''
    priority: float = 0.0

    def __post_init__(self) -> None:
        marketplace = _normalize(self.marketplace)
        query = _normalize(self.query_text)
        if not marketplace or not query:
            raise ValueError('marketplace e query_text são obrigatórios')
        if self.intent not in _ALLOWED_INTENTS:
            raise ValueError('intent inválida')
        if self.source_kind not in _ALLOWED_SOURCES:
            raise ValueError('source_kind inválido')
        if _is_generic(query) or _contains_private_data(query):
            raise ValueError('query comercial genérica ou insegura')
        object.__setattr__(self, 'marketplace', marketplace)
        object.__setattr__(self, 'query_text', query)
        object.__setattr__(self, 'brand', _normalize(self.brand))
        object.__setattr__(self, 'category_code', _normalize(self.category_code))


@dataclass(frozen=True)
class OpportunityPlan:
    marketplace: str
    opportunities: tuple[CommercialOpportunity, ...] = ()
    unplannable: tuple[dict[str, str], ...] = ()


def build_opportunity_plan(radar: dict[str, Any] | None, *, marketplace: str, limit: int = 20) -> OpportunityPlan:
    radar = radar or {}
    opportunities: list[CommercialOpportunity] = []
    unplannable: list[dict[str, str]] = []
    seen: set[str] = set()
    brands = sorted(radar.get('brands') or [], key=lambda item: (-int(item.get('observed_count') or 0), str(item.get('term') or '')))
    for item in brands:
        term = _normalize(item.get('term'))
        if not term:
            continue
        family = _normalize(item.get('family'))
        product = _BRAND_PRODUCTS.get(family)
        if not product:
            unplannable.append({'signal': term, 'reason': 'brand_without_product'})
            continue
        source = 'radar_brand' if int(item.get('observed_count') or 0) > 0 else 'priority_catalog'
        _append(opportunities, seen, marketplace, f'{term} {product}', 'brand_product', source, brand=term, priority=float(item.get('observed_count') or 0))
        if len(opportunities) >= limit:
            return OpportunityPlan(_normalize(marketplace), tuple(opportunities), tuple(unplannable))
    observed_terms = {_normalize(item.get('term')) for item in brands}
    for family, term in _PRIORITY_BRANDS:
        if term in observed_terms:
            continue
        _append(
            opportunities,
            seen,
            marketplace,
            f'{term} {_BRAND_PRODUCTS[family]}',
            'brand_product',
            'priority_catalog',
            brand=term,
            priority=1.0,
        )
        if len(opportunities) >= limit:
            return OpportunityPlan(_normalize(marketplace), tuple(opportunities), tuple(unplannable))
    for category, count in sorted((radar.get('categories') or {}).items(), key=lambda pair: -int(pair[1] or 0)):
        unplannable.append({'signal': str(category), 'reason': 'category_without_product'})
    return OpportunityPlan(_normalize(marketplace), tuple(opportunities[:limit]), tuple(unplannable))


def _append(target, seen, marketplace, query, intent, source, **kwargs):
    normalized = _normalize(query)
    if normalized in seen:
        return
    seen.add(normalized)
    try:
        target.append(CommercialOpportunity(marketplace, normalized, intent, source, **kwargs))
    except ValueError:
        return


def _normalize(value: Any) -> str:
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').lower().strip()
    return ' '.join(text.split())


def _is_generic(query: str) -> bool:
    tokens = set(re.findall(r'[a-z0-9]+', query))
    meaningful = tokens - _GENERIC
    return not meaningful or len(meaningful) < 2


def _contains_private_data(value: str) -> bool:
    return '@g.us' in value or 'http://' in value or 'https://' in value or 'raw_text' in value
