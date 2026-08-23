from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from apps.curation.services.settings import get_integer_setting
from apps.marketplaces.services.search_query_planner import SearchQuery, build_search_plan
from apps.marketplaces.services.search_provenance import sanitize_search_provenance
from apps.marketplaces.services.search_radar import build_search_radar
from scrapers import amazon, mercado_livre, shopee
from scrapers.category_targets import flatten_urls, get_targets

log = logging.getLogger(__name__)


CATEGORY_SCRAPING_FLAG = 'category_scraping_enabled'
DIRECTED_QUERY_FLAG = 'directed_search_enabled'
DIRECTED_QUERY_LIMIT = 6

# `DIRECTED_FALLBACK_CATEGORY_LIMIT = 2` foi removido no achado B1 (2026-08-18):
# truncava `flatten_urls()` sempre nas 2 primeiras URLs, na mesma ordem, todo ciclo,
# tornando as categorias do fim da lista (moda_masculina, saude_suplementacao...)
# inalcançáveis por construção. Hoje todas as URLs configuradas são varridas.


class MarketplaceScraper(Protocol):
    blocked: bool
    error_message: str
    pages_scraped: int

    def scrape_daily_deals(self, max_pages: int) -> list[dict]:
        ...


@dataclass(frozen=True)
class ScraperAdapter:
    marketplace_code: str
    scraper: MarketplaceScraper

    def collect(self, max_pages: int) -> list[dict]:
        """Coleta por união de três caminhos: busca direcionada + categorias + radar.

        Achado B1 (diagnóstico 2026-08-18). Até o commit 84e5071 a categoria era
        **fallback** da direcionada (`if not payloads`), o que na prática matou a
        coleta por categoria: onde a direcionada funciona (Amazon, Shopee) o ramo de
        categoria nunca mais rodou, e com ele foram junto todas as regras de
        qualidade de `category_targets` (min_discount, max_price, cycle_limit,
        incluindo o teto de exposição de suplementos). Os dois caminhos agora rodam
        sempre e o resultado é mesclado, deduplicado e filtrado de uma vez só.

        `scrape_daily_deals` continua como último recurso, para o caso de os dois
        caminhos voltarem vazios (marketplace bloqueado, flags desligadas).

        O terceiro ramo é o radar de concorrente (2026-08-21): ofertas divulgadas
        nos grupos observados, já resolvidas para o anúncio real por
        `resolve_competitor_links`. Entra na mesma união porque é coleta como
        qualquer outra — passa por dedup, filtros de categoria, normalização,
        curadoria e gates de diversidade sem tratamento especial. Existe para
        cobrir o que a coleta própria não alcança: com a busca por texto do ML
        bloqueada (B2), o pool do ML é o que cabe em 8 URLs de `/ofertas`.
        """
        payloads: list[dict] = []

        directed = self._directed_queries()
        if directed and hasattr(self.scraper, 'scrape_search_queries'):
            payloads.extend(self.scraper.scrape_search_queries(directed))
        directed_count = len(payloads)

        if _category_scraping_enabled() and hasattr(self.scraper, 'scrape_categories'):
            targets = flatten_urls(self.marketplace_code)
            if targets:
                payloads.extend(self.scraper.scrape_categories(
                    [(t.category_code, t.label, t.url, t.trust_hint) for t in targets],
                ))
        category_count = len(payloads) - directed_count

        payloads.extend(_competitor_radar_payloads(self.marketplace_code))
        radar_count = len(payloads) - directed_count - category_count

        if payloads:
            log.info(
                'collect_summary marketplace=%s directed=%d category=%d radar=%d total=%d',
                self.marketplace_code, directed_count, category_count, radar_count, len(payloads),
            )
            return _apply_category_filters(
                self.marketplace_code,
                _mark_unattributed_as_fallback(_deduplicate_payloads(payloads)),
            )
        return _mark_unattributed_as_fallback(self.scraper.scrape_daily_deals(max_pages=max_pages))

    def _directed_queries(self) -> tuple[SearchQuery, ...]:
        if not _directed_search_enabled():
            return ()
        try:
            radar = build_search_radar(lookback_hours=168, limit=30)
            plan = build_search_plan(radar, marketplaces=(self.marketplace_code,), max_queries=DIRECTED_QUERY_LIMIT)
            return plan.directed_queries
        except Exception:
            # Achado B3 (2026-08-18): esta exceção era engolida em silêncio. Uma falha
            # aqui desliga a busca direcionada e o sistema degrada para o fallback
            # genérico sem deixar rastro nenhum de por quê.
            log.warning('directed_queries_failed marketplace=%s', self.marketplace_code, exc_info=True)
            return ()

    @property
    def blocked(self) -> bool:
        return bool(getattr(self.scraper, 'blocked', False))

    @property
    def error_message(self) -> str:
        return str(getattr(self.scraper, 'error_message', '') or '')

    @property
    def pages_scraped(self) -> int:
        return int(getattr(self.scraper, 'pages_scraped', 0) or 0)


def _category_scraping_enabled() -> bool:
    return bool(get_integer_setting(CATEGORY_SCRAPING_FLAG, 0))


def _directed_search_enabled() -> bool:
    return bool(get_integer_setting(DIRECTED_QUERY_FLAG, 1))


def _competitor_radar_payloads(marketplace_code: str) -> list[dict]:
    """Ofertas que chegaram por link divulgado em grupo concorrente.

    Terceiro ramo da união (2026-08-21). Não faz rede: consome o que o comando
    `resolve_competitor_links` já resolveu e gravou em `ObservedOfferLink`,
    dentro da janela de frescor de preço. Desligado por padrão
    (`competitor_radar_enabled`).

    A falha aqui é contida pelo mesmo motivo do achado B3: um erro de leitura do
    radar não pode derrubar a coleta inteira do marketplace — mas também não
    pode sumir sem rastro.
    """
    try:
        from apps.market_intel.services.competitor_radar import build_radar_payloads, radar_enabled

        if not radar_enabled():
            return []
        return build_radar_payloads(marketplace_code)
    except Exception:
        log.warning('competitor_radar_payloads_failed marketplace=%s', marketplace_code, exc_info=True)
        return []


def _deduplicate_payloads(payloads: list[dict]) -> list[dict]:
    """Deduplica preservando os sinais dos dois caminhos de coleta.

    Com a união do achado B1 a mesma oferta passa a poder chegar pelas duas vias, e
    cada uma traz um sinal que a outra não tem: a direcionada traz
    `search_provenance` (qual demanda observada motivou a busca) e a categoria traz
    `category_hint` (que alimenta o classifier e os filtros de categoria). Descartar
    a duplicata inteira perderia um dos dois, então mantemos a primeira ocorrência e
    completamos apenas os campos que faltam nela.
    """
    seen: dict[str, dict] = {}
    result: list[dict] = []
    for payload in payloads:
        key = str(payload.get('external_id') or payload.get('id') or payload.get('product_url') or payload.get('url') or payload.get('title') or '')
        kept = seen.get(key)
        if kept is not None:
            for field in ('category_hint', 'search_provenance'):
                if not kept.get(field) and payload.get(field):
                    kept[field] = payload[field]
            continue
        seen[key] = payload
        result.append(payload)
    log.info('directed_search_dedup input=%d output=%d', len(payloads), len(result))
    return result


def _mark_unattributed_as_fallback(payloads: list[dict]) -> list[dict]:
    for payload in payloads:
        if not payload.get('search_provenance'):
            payload['search_provenance'] = sanitize_search_provenance({
                'source_kind': 'generic_fallback',
                'marketplace': payload.get('marketplace_code', ''),
            })
    return payloads


def _apply_category_filters(marketplace_code: str, payloads: list[dict]) -> list[dict]:
    cfg = get_targets(marketplace_code)
    if not cfg:
        return payloads

    counters: dict[str, int] = {}
    dropped: dict[str, int] = {}
    out: list[dict] = []

    for payload in payloads:
        category_code = payload.get('category_hint', '')
        rules = cfg.get(category_code)
        if rules is None:
            out.append(payload)
            continue

        discount = _payload_number(payload, 'desconto_pct', 'discount_pct')
        price = _payload_number(payload, 'preco', 'price', 'current_price')
        if discount < rules.get('min_discount', 0):
            dropped[f'{category_code}:min_discount'] = dropped.get(f'{category_code}:min_discount', 0) + 1
            continue
        max_price = rules.get('max_price')
        if max_price is not None and price > max_price:
            dropped[f'{category_code}:max_price'] = dropped.get(f'{category_code}:max_price', 0) + 1
            continue
        cycle_limit = rules.get('cycle_limit', 0)
        if cycle_limit and counters.get(category_code, 0) >= cycle_limit:
            dropped[f'{category_code}:cycle_limit'] = dropped.get(f'{category_code}:cycle_limit', 0) + 1
            continue

        counters[category_code] = counters.get(category_code, 0) + 1
        out.append(payload)

    # Reposto no achado B1 (2026-08-18): este log existia antes do commit 84e5071 e
    # foi removido junto com a regressão, apagando a única visibilidade operacional
    # de quantas ofertas cada categoria rendeu e por qual regra as descartadas caíram.
    log.info(
        'category_scraping_summary marketplace=%s in=%d kept=%d per_category=%s dropped=%s',
        marketplace_code, len(payloads), len(out), counters, dropped,
    )
    return out


def _payload_number(payload: dict, *keys: str) -> float:
    for key in keys:
        value = payload.get(key)
        if value in (None, ''):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def build_adapter(marketplace_code: str) -> ScraperAdapter:
    adapters = {
        'mercadolivre': lambda: mercado_livre.build_from_env(),
        'amazon': lambda: amazon.build_from_env(),
        'shopee': lambda: shopee.build_from_env(),
    }
    try:
        scraper = adapters[marketplace_code]()
    except KeyError as exc:
        raise ValueError(f'Marketplace sem adapter de scraping: {marketplace_code}') from exc
    return ScraperAdapter(marketplace_code=marketplace_code, scraper=scraper)
