import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_WA_SERVICE_URL = 'http://127.0.0.1:8787'
DEFAULT_EVOLUTION_ADAPTER_URL = 'http://127.0.0.1:8788'


class WhatsAppObserverClientError(Exception):
    pass


class WhatsAppObserverClient:
    def __init__(self, base_url: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = (base_url or resolve_whatsapp_observer_base_url()).rstrip('/')
        if not self.base_url:
            self.base_url = DEFAULT_WA_SERVICE_URL
        self.timeout = timeout
        self.service_label = resolve_whatsapp_observer_service_label()

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
            message = payload.get('error') or f'{self.service_label} observer retornou HTTP {exc.code}.'
            raise WhatsAppObserverClientError(str(message)) from exc
        except URLError as exc:
            raise WhatsAppObserverClientError(f'{self.service_label} indisponível: {exc.reason}') from exc
        except TimeoutError as exc:
            raise WhatsAppObserverClientError(f'Tempo esgotado ao chamar {self.service_label} observer.') from exc

    def _decode(self, raw_body: bytes) -> dict:
        if not raw_body:
            return {}
        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise WhatsAppObserverClientError(f'Resposta inválida do {self.service_label} observer.') from exc
        if not isinstance(payload, dict):
            raise WhatsAppObserverClientError(f'Resposta inesperada do {self.service_label} observer.')
        return payload


def resolve_whatsapp_observer_base_url() -> str:
    provider = str(getattr(settings, 'WA_PROVIDER', 'baileys') or 'baileys').strip().lower()
    if provider == 'evolution':
        return str(getattr(settings, 'EVOLUTION_ADAPTER_URL', '') or DEFAULT_EVOLUTION_ADAPTER_URL)
    return str(getattr(settings, 'WA_SERVICE_URL', '') or DEFAULT_WA_SERVICE_URL)


def resolve_whatsapp_observer_service_label() -> str:
    provider = str(getattr(settings, 'WA_PROVIDER', 'baileys') or 'baileys').strip().lower()
    if provider == 'evolution':
        return 'Evolution adapter'
    return 'wa_service'
