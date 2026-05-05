from dataclasses import dataclass
from typing import Protocol

from scrapers import amazon, mercado_livre


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


def build_adapter(marketplace_code: str) -> ScraperAdapter:
    adapters = {
        'mercadolivre': lambda: mercado_livre.build_from_env(),
        'amazon': lambda: amazon.build_from_env(),
    }
    try:
        scraper = adapters[marketplace_code]()
    except KeyError as exc:
        raise ValueError(f'Marketplace sem adapter de scraping: {marketplace_code}') from exc
    return ScraperAdapter(marketplace_code=marketplace_code, scraper=scraper)
