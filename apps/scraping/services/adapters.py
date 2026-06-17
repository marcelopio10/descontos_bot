import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from apps.curation.services.settings import get_integer_setting
from scrapers import amazon, mercado_livre, shopee
from scrapers.category_targets import flatten_urls, get_targets


log = logging.getLogger(__name__)

CATEGORY_SCRAPING_FLAG = 'category_scraping_enabled'


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
        if _category_scraping_enabled() and hasattr(self.scraper, 'scrape_categories'):
            targets = flatten_urls(self.marketplace_code)
            if targets:
                payloads = self.scraper.scrape_categories(
                    [(t.category_code, t.label, t.url, t.trust_hint) for t in targets],
                )
                return _apply_category_filters(self.marketplace_code, payloads)
        return self.scraper.scrape_daily_deals(max_pages=max_pages)

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


def _apply_category_filters(marketplace_code: str, payloads: list[dict]) -> list[dict]:
    cfg = get_targets(marketplace_code)
    if not cfg:
        return payloads

    counters: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    dropped: dict[str, int] = defaultdict(int)

    for payload in payloads:
        category_code = payload.get('category_hint', '')
        rules = cfg.get(category_code)
        if rules is None:
            out.append(payload)
            continue

        discount = _payload_number(payload, 'desconto_pct', 'discount_pct')
        price = _payload_number(payload, 'preco', 'price')

        if discount < rules.get('min_discount', 0):
            dropped[f'{category_code}:min_discount'] += 1
            continue
        max_price = rules.get('max_price')
        if max_price is not None and price > max_price:
            dropped[f'{category_code}:max_price'] += 1
            continue

        cycle_limit = rules.get('cycle_limit', 0)
        if cycle_limit and counters[category_code] >= cycle_limit:
            dropped[f'{category_code}:cycle_limit'] += 1
            continue

        counters[category_code] += 1
        out.append(payload)

    log.info(
        'category_scraping_summary marketplace=%s kept=%d per_category=%s dropped=%s',
        marketplace_code, len(out), dict(counters), dict(dropped),
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
