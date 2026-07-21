from abc import ABC, abstractmethod
import logging
import time

import requests
try:
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests.exceptions import RequestException as CffiRequestException
    CURL_CFFI_AVAILABLE = True
except ImportError:
    cffi_requests = requests  # fallback; pode falhar em TLS fingerprinting
    CffiRequestException = requests.RequestException
    CURL_CFFI_AVAILABLE = False


log = logging.getLogger(__name__)

# `requests` e `curl_cffi` têm hierarquias de exceção independentes (uma não é
# subclasse da outra), então os scrapers que podem rodar sobre qualquer uma das
# duas libs (via `build_impersonated_session`) precisam capturar as duas.
HTTP_EXCEPTIONS = (requests.RequestException, CffiRequestException)


def build_impersonated_session(impersonate: str = 'chrome124'):
    """Cria uma sessão HTTP com impersonação de TLS via curl_cffi (contorna
    bloqueio anti-bot que identifica `requests` puro pelo fingerprint TLS do
    handshake, independente de User-Agent/headers).

    Fallback gracioso para `requests.Session()` puro se curl_cffi não estiver
    instalado — loga aviso porque o scraper fica mais vulnerável a bloqueio
    por fingerprint nesse modo.
    """
    if CURL_CFFI_AVAILABLE:
        return cffi_requests.Session(impersonate=impersonate)
    log.warning(
        'curl_cffi não disponível — usando requests padrão '
        '(mais vulnerável a bloqueio por TLS fingerprint).',
    )
    return cffi_requests.Session()


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
            except HTTP_EXCEPTIONS as exc:
                last_exc = exc
                log.warning('Tentativa %d falhou para %s: %s', attempt, url, exc)
        if last_exc:
            raise last_exc
        raise RuntimeError('Falha inesperada no retry HTTP.')
