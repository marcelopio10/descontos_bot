from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable

from apps.marketplaces.services.search_provenance import ALLOWED_SEARCH_SOURCES

_GENERIC_TERMS = frozenset({'cupom', 'desconto', 'oferta', 'promoção', 'promocao'})
_UNSAFE_RE = re.compile(r'(@g\.us|https?://|raw_text|sender_hash|group_jid)', re.IGNORECASE)

# Achado 2026-08-21 (origem da "impressão de repetição"): o termo de produto era
# fixo por família — TODA marca de moda virava a query "<marca> tênis". Com 12
# marcas de moda no radar, o plano de busca era estruturalmente um plano de
# tênis, e o pool refletia isso (52 das 386 ofertas coletadas em 7 dias eram
# tênis, 13%). Gate de curadoria nenhum conserta um pool que já chega enviesado:
# ele só reduziria volume. Aqui a marca passa a variar o produto buscado.
#
# A escolha é por ÍNDICE da marca dentro da família (determinística, sem
# random): marcas vizinhas da mesma família nunca pedem o mesmo produto e o
# plano é reproduzível entre execuções — mesma propriedade que o repo já adota
# em message_builder._variant_index.
FAMILY_PRODUCT_TERMS: dict[str, tuple[str, ...]] = {
    'moda': ('tênis', 'camiseta', 'moletom', 'bermuda', 'mochila', 'jaqueta', 'chinelo', 'meia'),
    'perfumes_arabes': ('perfume', 'perfume masculino', 'perfume feminino'),
    'suplementos': ('creatina', 'whey protein', 'colágeno', 'multivitamínico', 'pré treino'),
    'tecnologia': ('fone de ouvido', 'caixa de som', 'monitor', 'smartwatch', 'carregador', 'teclado'),
    'casa': ('air fryer', 'liquidificador', 'jogo de panelas', 'aspirador', 'cafeteira', 'ventilador'),
}
_FALLBACK_FAMILY_PRODUCT_TERM = 'oferta'
_NO_FAMILY_PRODUCT_TERM = 'produto'


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
        family_positions: dict[str, int] = {}
        for item in brands[:brand_budget]:
            term = _normalize(item.get('term'))
            if not term or term in _GENERIC_TERMS:
                continue
            family = _normalize(item.get('family'))
            source = 'radar_brand' if int(item.get('observed_count') or 0) > 0 else 'priority_catalog'
            position = family_positions.get(family, 0)
            family_positions[family] = position + 1
            text = f'{term} {_family_product_term(family, position)}'
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


def _family_product_term(family: str, position: int) -> str:
    """Produto buscado para a n-ésima marca de uma família.

    Sem família conhecida mantém o comportamento antigo ("<marca> produto");
    família sem lista própria cai em "oferta". Só as famílias mapeadas em
    FAMILY_PRODUCT_TERMS rotacionam.
    """
    if not family:
        return _NO_FAMILY_PRODUCT_TERM
    terms = FAMILY_PRODUCT_TERMS.get(family)
    if not terms:
        return _FALLBACK_FAMILY_PRODUCT_TERM
    return terms[position % len(terms)]


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
