from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


class CouponSourceError(Exception):
    pass


@dataclass(frozen=True)
class SourcePage:
    url: str
    markdown: str
    provider: str
    error: str = ''


class FirecrawlClient:
    def __init__(self, keys: list[str] | None = None, timeout: int = 30):
        raw = os.environ.get('FIRECRAWL_API_KEYS', '')
        configured = keys or [os.environ.get('FIRECRAWL_API_KEY', ''), *raw.split(',')]
        self.keys = list(dict.fromkeys(key.strip() for key in configured if key.strip()))
        self.timeout = timeout

    def search(self, query: str, limit: int = 5) -> list[SourcePage]:
        errors = []
        for key in self.keys:
            try:
                payload = self._request('/search', {'query': query, 'limit': limit}, key)
                pages = []
                for row in payload.get('data', payload.get('web', [])) or []:
                    url = str(row.get('url') or '').strip()
                    if url:
                        pages.append(SourcePage(url, str(row.get('markdown') or row.get('description') or ''), 'firecrawl'))
                if pages:
                    return pages
                errors.append('firecrawl sem resultados')
            except Exception as exc:
                errors.append(f'firecrawl:{type(exc).__name__}')
        try:
            return self._http_search(query, limit)
        except Exception as exc:
            raise CouponSourceError('; '.join(errors + [f'http:{type(exc).__name__}'])) from exc

    def scrape(self, url: str) -> SourcePage:
        errors = []
        for key in self.keys:
            try:
                payload = self._request('/scrape', {'url': url, 'formats': ['markdown']}, key)
                data = payload.get('data') or payload
                markdown = str(data.get('markdown') or data.get('content') or '')
                if markdown:
                    return SourcePage(url, markdown, 'firecrawl')
                errors.append('firecrawl sem conteúdo')
            except Exception as exc:
                errors.append(f'firecrawl:{type(exc).__name__}')
        try:
            request = Request(url, headers={'User-Agent': 'descontos.bot coupon validator/1.0'})
            with urlopen(request, timeout=self.timeout) as response:
                return SourcePage(url, response.read().decode('utf-8', errors='replace'), 'http_fallback')
        except Exception as exc:
            raise CouponSourceError('; '.join(errors + [f'http:{type(exc).__name__}'])) from exc

    def _request(self, path: str, body: dict, key: str) -> dict:
        request = Request(
            f'https://api.firecrawl.dev/v1{path}',
            data=json.dumps(body).encode(),
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            method='POST',
        )
        with urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode())
        if not isinstance(data, dict):
            raise CouponSourceError('resposta Firecrawl inválida')
        return data

    def _http_search(self, query: str, limit: int) -> list[SourcePage]:
        url = f'https://html.duckduckgo.com/html/?q={quote_plus(query)}'
        request = Request(url, headers={'User-Agent': 'descontos.bot coupon collector/1.0'})
        with urlopen(request, timeout=self.timeout) as response:
            html = response.read().decode('utf-8', errors='replace')
        import re
        rows = re.findall(r'nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        return [SourcePage(re.sub(r'<.*?>', '', url), re.sub(r'<.*?>', '', title), 'duckduckgo_fallback') for url, title in rows[:limit]]
