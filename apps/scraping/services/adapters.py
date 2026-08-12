from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from apps.curation.services.settings import get_integer_setting
from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity, build_opportunity_plan
from apps.marketplaces.services.commercial_validator import validate_commercial_candidate
from apps.marketplaces.services.search_provenance import sanitize_search_provenance
from apps.marketplaces.services.search_radar import build_search_radar
from scrapers import amazon, mercado_livre, shopee
from scrapers.category_targets import flatten_urls, get_targets

log = logging.getLogger(__name__)


CATEGORY_SCRAPING_FLAG = 'category_scraping_enabled'
DIRECTED_QUERY_FLAG = 'directed_search_enabled'
DIRECTED_QUERY_LIMIT = 6
DIRECTED_FALLBACK_CATEGORY_LIMIT = 2


class MarketplaceScraper(Protocol):
    blocked: bool
    error_message: str
    pages_scraped: int

    def scrape_daily_deals(self, max_pages: int) -> list[dict]:
        ...

    def scrape_search_queries(self, queries: tuple[CommercialOpportunity, ...]) -> list[dict]:
        ...


@dataclass(frozen=True)
class ScraperAdapter:
    marketplace_code: str
    scraper: MarketplaceScraper

    def collect(self, max_pages: int) -> list[dict]:
        if _directed_search_enabled():
            directed = self._directed_opportunities()
            if not hasattr(self.scraper, 'scrape_search_queries'):
                raise RuntimeError(f'{self.marketplace_code} não implementa busca comercial direcionada')
            payloads = self.scraper.scrape_search_queries(directed)
            payloads = _attach_execution_provenance(payloads, directed)
            payloads = _validate_directed_payloads(payloads, directed)
            log.info(
                'commercial_search.completed marketplace=%s opportunities=%d offers=%d',
                self.marketplace_code,
                len(directed),
                len(payloads),
            )
            return _deduplicate_payloads(payloads)

        return self._collect_legacy(max_pages)

    def _collect_legacy(self, max_pages: int) -> list[dict]:
        payloads: list[dict] = []
        if not payloads and _category_scraping_enabled() and hasattr(self.scraper, 'scrape_categories'):
            targets = flatten_urls(self.marketplace_code)
            if targets:
                payloads.extend(self.scraper.scrape_categories(
                    [(t.category_code, t.label, t.url, t.trust_hint) for t in targets[:DIRECTED_FALLBACK_CATEGORY_LIMIT]],
                ))
                return _apply_category_filters(self.marketplace_code, _mark_unattributed_as_fallback(_deduplicate_payloads(payloads)))
        if payloads:
            return _mark_unattributed_as_fallback(_deduplicate_payloads(payloads))
        return _mark_unattributed_as_fallback(self.scraper.scrape_daily_deals(max_pages=max_pages))

    def _directed_opportunities(self) -> tuple[CommercialOpportunity, ...]:
        radar = build_search_radar(lookback_hours=168, limit=30)
        plan = build_opportunity_plan(radar, marketplace=self.marketplace_code, limit=DIRECTED_QUERY_LIMIT)
        if not plan.opportunities:
            log.warning(
                'commercial_search.no_opportunities marketplace=%s unplannable=%s',
                self.marketplace_code,
                plan.unplannable,
            )
        return plan.opportunities

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


def _deduplicate_payloads(payloads: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for payload in payloads:
        key = str(payload.get('external_id') or payload.get('id') or payload.get('product_url') or payload.get('url') or payload.get('title') or '')
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    log.info('directed_search_dedup input=%d output=%d', len(payloads), len(result))
    return result


def _validate_directed_payloads(payloads: list[dict], opportunities: tuple[CommercialOpportunity, ...]) -> list[dict]:
    by_query = {item.query_text: item for item in opportunities}
    accepted: list[dict] = []
    rejected: dict[str, int] = {}
    for payload in payloads:
        provenance = payload.get('search_provenance') or {}
        opportunity = by_query.get(str(provenance.get('query_text') or '').strip().lower())
        if opportunity is None:
            rejected['missing_provenance'] = rejected.get('missing_provenance', 0) + 1
            continue
        validation = validate_commercial_candidate(payload, opportunity)
        if not validation.accepted:
            rejected[validation.reason] = rejected.get(validation.reason, 0) + 1
            continue
        accepted.append(payload)
    log.info('commercial_search.validation accepted=%d rejected=%s', len(accepted), rejected)
    return accepted


def _attach_execution_provenance(payloads: list[dict], opportunities: tuple[CommercialOpportunity, ...]) -> list[dict]:
    by_query = {item.query_text: item for item in opportunities}
    for payload in payloads:
        provenance = dict(payload.get('search_provenance') or {})
        opportunity = by_query.get(str(provenance.get('query_text') or '').strip().lower())
        if opportunity is None:
            continue
        provenance.update({
            'opportunity_id': _opportunity_id(opportunity),
            'query_hash': _query_hash(opportunity),
        })
        payload['search_provenance'] = sanitize_search_provenance(provenance)
    return payloads


def _opportunity_id(opportunity: CommercialOpportunity) -> str:
    return f'{opportunity.marketplace}:{opportunity.source_kind}:{_query_hash(opportunity)}'


def _query_hash(opportunity: CommercialOpportunity) -> str:
    import hashlib
    return hashlib.sha256(f'{opportunity.marketplace}:{opportunity.query_text}'.encode()).hexdigest()[:16]


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
