from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable

from apps.marketplaces.services.search_provenance import ALLOWED_SEARCH_SOURCES

_GENERIC_TERMS = frozenset({'cupom', 'desconto', 'oferta', 'promoção', 'promocao'})
_UNSAFE_RE = re.compile(r'(@g\.us|https?://|raw_text|sender_hash|group_jid)', re.IGNORECASE)


@dataclass(frozen=True)
class SearchQuery:
    marketplace: str
    query_text: str
    source_kind: str
    category_code: str = ''
    price_band: str = ''
    brand: str = ''
    priority: float = 0.0

    def __post_init__(self) -> None:
        marketplace = _normalize(self.marketplace)
        query = _normalize(self.query_text)
        source = str(self.source_kind).strip()
        if not marketplace or not query:
            raise ValueError('marketplace e query_text são obrigatórios')
        if source not in ALLOWED_SEARCH_SOURCES:
            raise ValueError(f'origem de busca inválida: {source}')
        if _UNSAFE_RE.search(query) or any(token == query for token in _GENERIC_TERMS):
            raise ValueError('query de busca insegura ou genérica')
        object.__setattr__(self, 'marketplace', marketplace)
        object.__setattr__(self, 'query_text', query)
        object.__setattr__(self, 'source_kind', source)


@dataclass(frozen=True)
class SearchPlan:
    queries: tuple[SearchQuery, ...] = ()
    fallback_queries: tuple[SearchQuery, ...] = ()
    blocked_queries: tuple[dict[str, str], ...] = ()

    @property
    def directed_queries(self) -> tuple[SearchQuery, ...]:
        return tuple(query for query in self.queries if query.source_kind != 'generic_fallback')

    def as_dict(self) -> dict[str, Any]:
        return {
            'planned_query_count': len(self.queries) + len(self.fallback_queries),
            'directed_query_count': len(self.directed_queries),
            'fallback_query_count': len(self.fallback_queries),
            'blocked_query_count': len(self.blocked_queries),
            'queries': [query.__dict__ for query in self.queries],
            'fallback_queries': [query.__dict__ for query in self.fallback_queries],
            'blocked_queries': list(self.blocked_queries),
        }


def build_search_plan(
    radar: dict[str, Any] | None,
    *,
    marketplaces: Iterable[str] = ('amazon', 'mercadolivre', 'shopee'),
    max_queries: int = 30,
) -> SearchPlan:
    radar = radar or {}
    queries: list[SearchQuery] = []
    fallback: list[SearchQuery] = []
    seen: set[tuple[str, str]] = set()
    marketplace_values = tuple(_normalize(value) for value in marketplaces if _normalize(value))
    brands = sorted(radar.get('brands') or [], key=lambda item: (-int(item.get('observed_count') or 0), str(item.get('term') or '')))
    categories = sorted((radar.get('categories') or {}).items(), key=lambda item: -int(item[1] or 0))
    price_bands = sorted((radar.get('price_bands') or {}).items(), key=lambda item: -int(item[1] or 0))
    for marketplace in marketplace_values:
        brand_budget = max(1, max_queries // 2)
        category_budget = max(1, max_queries // 3)
        price_budget = max(1, max_queries - brand_budget - category_budget)
        for item in brands[:brand_budget]:
            term = _normalize(item.get('term'))
            if not term or term in _GENERIC_TERMS:
                continue
            family = _normalize(item.get('family'))
            source = 'radar_brand' if int(item.get('observed_count') or 0) > 0 else 'priority_catalog'
            text = f'{term} {"tênis" if family == "moda" else "oferta" if family else "produto"}'
            _append_query(queries, seen, marketplace, text, source, brand=term, priority=float(item.get('observed_count') or 0))
        for category, count in categories[:category_budget]:
            term = _category_term(category)
            if term:
                _append_query(queries, seen, marketplace, term, 'radar_category', category_code=category, priority=float(count or 0))
        for band, count in price_bands[:price_budget]:
            term = _price_band_term(band)
            if term:
                _append_query(queries, seen, marketplace, term, 'radar_price_band', price_band=band, priority=float(count or 0))
        if len(queries) >= max_queries:
            break
    if not queries:
        for marketplace in marketplace_values:
            try:
                fallback.append(SearchQuery(marketplace=marketplace, query_text='ofertas elegíveis', source_kind='generic_fallback'))
            except ValueError:
                continue
    return SearchPlan(queries=tuple(queries[:max_queries]), fallback_queries=tuple(fallback[:max(1, max_queries // 10)]))


def _append_query(queries, seen, marketplace, text, source, **kwargs):
    key = (marketplace, _normalize(text))
    if key in seen:
        return
    seen.add(key)
    try:
        queries.append(SearchQuery(marketplace=marketplace, query_text=text, source_kind=source, **kwargs))
    except ValueError:
        return


def _category_term(value: Any) -> str:
    text = _normalize(value).replace('categoria:', '').replace('_', ' ')
    return text if text and text not in _GENERIC_TERMS else ''


def _price_band_term(value: Any) -> str:
    text = _normalize(value).replace('_', ' ')
    return f'ofertas {text}' if text and text not in _GENERIC_TERMS else ''


def _normalize(value: Any) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).strip().lower()
    return ' '.join(text.split())
