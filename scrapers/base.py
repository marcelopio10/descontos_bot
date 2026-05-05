from abc import ABC, abstractmethod
import logging
import time

import requests


log = logging.getLogger(__name__)


class BaseScraper(ABC):
    @abstractmethod
    def scrape_daily_deals(self, max_pages: int):
        raise NotImplementedError

    @abstractmethod
    def _parse_item(self, card):
        raise NotImplementedError

    @staticmethod
    def is_blocked(html: str) -> bool:
        content = html.lower()
        blocked_markers = [
            'captcha',
            'captcha-page',
            'robot check',
            'verifique que você não é um robô',
        ]
        return any(marker in content for marker in blocked_markers)

    def fetch_with_retry(self, session, url: str, headers: dict, timeout: int = 20) -> requests.Response:
        last_exc = None
        for attempt, backoff in enumerate([0, 2, 4, 8], start=1):
            if backoff:
                time.sleep(backoff)
            try:
                response = session.get(url, headers=headers, timeout=timeout)
                if response.status_code < 500:
                    return response
                last_exc = requests.HTTPError(f'HTTP {response.status_code}')
                log.warning('Tentativa %d falhou para %s: HTTP %s', attempt, url, response.status_code)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning('Tentativa %d falhou para %s: %s', attempt, url, exc)
        if last_exc:
            raise last_exc
        raise RuntimeError('Falha inesperada no retry HTTP.')
