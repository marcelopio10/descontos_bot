import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

DEFAULT_TIMEOUT_SECONDS = 30


class WhatsAppObserverClientError(Exception):
    pass


class WhatsAppObserverClient:
    def __init__(self, base_url: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = (base_url or getattr(settings, 'WA_SERVICE_URL', '') or 'http://127.0.0.1:8787').rstrip('/')
        self.timeout = timeout

    def groups(self) -> dict:
        return self._request('GET', '/observer/groups')

    def collect(self) -> dict:
        return self._request('POST', '/observer/collect', {})

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        body = json.dumps(data).encode('utf-8') if data is not None else None
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(f'{self.base_url}{path}', data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return self._decode(response.read())
        except HTTPError as exc:
            payload = self._decode(exc.read())
            raise WhatsAppObserverClientError(str(payload.get('error') or f'HTTP {exc.code}')) from exc
        except URLError as exc:
            raise WhatsAppObserverClientError(f'wa_service indisponível: {exc.reason}') from exc
        except TimeoutError as exc:
            raise WhatsAppObserverClientError('Tempo esgotado ao chamar wa_service observer.') from exc

    def _decode(self, raw_body: bytes) -> dict:
        if not raw_body:
            return {}
        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise WhatsAppObserverClientError('Resposta inválida do wa_service observer.') from exc
        if not isinstance(payload, dict):
            raise WhatsAppObserverClientError('Resposta inesperada do wa_service observer.')
        return payload
