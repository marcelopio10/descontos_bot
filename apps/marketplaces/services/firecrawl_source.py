from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.marketplaces.services.source_contracts import SourceQuery, SourceResult, SourceState


@dataclass(frozen=True)
class FirecrawlConfig:
    enabled: bool = False
    max_pages_per_cycle: int = 3
    timeout_seconds: int = 30


class FirecrawlSource:
    """Fonte pública opcional; nunca contorna login, CAPTCHA ou bloqueio."""

    def __init__(self, *, config: FirecrawlConfig | None = None, scraper: Callable[..., Any] | None = None):
        self.config = config or FirecrawlConfig()
        self._scraper = scraper

    def execute(self, query: SourceQuery) -> SourceResult:
        if not self.config.enabled:
            return SourceResult(query=query, state=SourceState.BLOCKED, error_code='firecrawl_disabled')
        if self._scraper is None:
            return SourceResult(query=query, state=SourceState.FAILED, error_code='firecrawl_not_configured')
        try:
            data = self._scraper(query.query_text, timeout=self.config.timeout_seconds)
        except Exception as exc:
            return SourceResult(query=query, state=SourceState.FAILED, error_code='firecrawl_exception', error_message=type(exc).__name__)
        offers = tuple(_sanitize_candidate(item) for item in (data or []) if isinstance(item, dict))
        if not offers:
            return SourceResult(query=query, state=SourceState.EMPTY)
        return SourceResult(query=query, state=SourceState.EXECUTED, offers=offers)


def _sanitize_candidate(item: dict[str, Any]) -> dict[str, Any]:
    allowed = ('title', 'product_url', 'current_price', 'original_price', 'discount_pct', 'image_url', 'seller', 'rating', 'review_count', 'source_url')
    result = {key: item.get(key) for key in allowed if item.get(key) not in (None, '')}
    for key in ('title', 'seller', 'source_url'):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = value[:500]
    return result
