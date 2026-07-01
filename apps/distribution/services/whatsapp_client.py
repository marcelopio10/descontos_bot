import json
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils.dateparse import parse_datetime


DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_WA_SERVICE_URL = 'http://127.0.0.1:8787'
DEFAULT_EVOLUTION_ADAPTER_URL = 'http://127.0.0.1:8788'


class WhatsAppClientError(Exception):
    pass


@dataclass(frozen=True)
class WhatsAppStatus:
    connected: bool
    jid: str | None


@dataclass(frozen=True)
class WhatsAppSendResult:
    success: bool
    message_id: str
    sent_at: datetime | None
    error_message: str


class WhatsAppClient:
    def __init__(self, base_url: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = (base_url or resolve_whatsapp_base_url()).rstrip('/')
        if not self.base_url:
            self.base_url = DEFAULT_WA_SERVICE_URL
        self.timeout = timeout
        self.service_label = resolve_whatsapp_service_label()

    def get_status(self) -> WhatsAppStatus:
        payload = self._request('GET', '/status')
        return WhatsAppStatus(
            connected=bool(payload.get('connected')),
            jid=payload.get('jid') or None,
        )

    def send_message(
        self,
        destination: str,
        message: str,
        image_url: str = '',
    ) -> WhatsAppSendResult:
        data = {
            'destination': destination,
            'message': message,
        }
        if image_url:
            data['image_url'] = image_url

        payload = self._request(
            'POST',
            '/send-message',
            data,
        )
        sent_at = payload.get('sent_at')
        return WhatsAppSendResult(
            success=bool(payload.get('success')),
            message_id=str(payload.get('message_id') or ''),
            sent_at=parse_datetime(sent_at) if sent_at else None,
            error_message=str(payload.get('error') or ''),
        )

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f'{self.base_url}{path}'
        body = None
        headers = {'Accept': 'application/json'}

        if data is not None:
            body = json.dumps(data).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        request = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                return self._decode_response(response.read())
        except HTTPError as exc:
            payload = self._decode_response(exc.read())
            message = payload.get('error') or f'{self.service_label} retornou HTTP {exc.code}.'
            raise WhatsAppClientError(str(message)) from exc
        except URLError as exc:
            raise WhatsAppClientError(f'{self.service_label} indisponível: {exc.reason}') from exc
        except TimeoutError as exc:
            raise WhatsAppClientError(f'Tempo esgotado ao chamar {self.service_label}.') from exc

    def _decode_response(self, raw_body: bytes) -> dict:
        if not raw_body:
            return {}

        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except json.JSONDecodeError as exc:
            raise WhatsAppClientError(f'Resposta inválida do {self.service_label}.') from exc

        if not isinstance(payload, dict):
            raise WhatsAppClientError(f'Resposta inesperada do {self.service_label}.')

        return payload


def resolve_whatsapp_base_url() -> str:
    provider = str(getattr(settings, 'WA_PROVIDER', 'baileys') or 'baileys').strip().lower()
    if provider == 'evolution':
        return str(getattr(settings, 'EVOLUTION_ADAPTER_URL', '') or DEFAULT_EVOLUTION_ADAPTER_URL)
    return str(getattr(settings, 'WA_SERVICE_URL', '') or DEFAULT_WA_SERVICE_URL)


def resolve_whatsapp_service_label() -> str:
    provider = str(getattr(settings, 'WA_PROVIDER', 'baileys') or 'baileys').strip().lower()
    if provider == 'evolution':
        return 'Evolution adapter'
    return 'wa_service'
