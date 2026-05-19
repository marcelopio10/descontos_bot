import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


DEFAULT_TIMEOUT_SECONDS = 15
MAX_RETRIES_5XX = 3
TELEGRAM_API_BASE = 'https://api.telegram.org'

logger = logging.getLogger('apps.distribution.telegram')


class TelegramClientError(Exception):
    pass


@dataclass(frozen=True)
class TelegramSendResult:
    success: bool
    message_id: str
    sent_at: datetime | None
    error_message: str


class TelegramClient:
    def __init__(
        self,
        token: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.token = token if token is not None else getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        self.timeout = timeout
        if not self.token:
            raise TelegramClientError('TELEGRAM_BOT_TOKEN não configurado.')

    def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption_html: str,
        inline_keyboard: list[list[dict]] | None = None,
    ) -> TelegramSendResult:
        payload = {
            'chat_id': chat_id,
            'photo': photo_url,
            'caption': caption_html,
            'parse_mode': 'HTML',
        }
        if inline_keyboard:
            payload['reply_markup'] = {'inline_keyboard': inline_keyboard}
        return self._send('sendPhoto', payload)

    def send_message(
        self,
        chat_id: str,
        text_html: str,
        inline_keyboard: list[list[dict]] | None = None,
        disable_web_page_preview: bool = True,
    ) -> TelegramSendResult:
        payload = {
            'chat_id': chat_id,
            'text': text_html,
            'parse_mode': 'HTML',
            'disable_web_page_preview': disable_web_page_preview,
        }
        if inline_keyboard:
            payload['reply_markup'] = {'inline_keyboard': inline_keyboard}
        return self._send('sendMessage', payload)

    def pin_chat_message(
        self,
        chat_id: str,
        message_id: int | str,
        disable_notification: bool = True,
    ) -> bool:
        payload = {
            'chat_id': chat_id,
            'message_id': int(message_id),
            'disable_notification': disable_notification,
        }
        response = self._request('pinChatMessage', payload)
        return bool(response.get('result'))

    def get_chat(self, chat_id: str) -> dict:
        return self._request('getChat', {'chat_id': chat_id}).get('result') or {}

    def _send(self, method: str, payload: dict) -> TelegramSendResult:
        try:
            response = self._request(method, payload)
        except TelegramClientError as exc:
            return TelegramSendResult(
                success=False,
                message_id='',
                sent_at=None,
                error_message=str(exc),
            )

        result = response.get('result') or {}
        message_id = result.get('message_id')
        unix_date = result.get('date')
        sent_at = None
        if isinstance(unix_date, (int, float)):
            sent_at = datetime.fromtimestamp(int(unix_date), tz=dt_timezone.utc)
        return TelegramSendResult(
            success=True,
            message_id=str(message_id or ''),
            sent_at=sent_at,
            error_message='',
        )

    def _request(self, method: str, payload: dict) -> dict:
        url = f'{TELEGRAM_API_BASE}/bot{self.token}/{method}'
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        attempts = 0
        backoff = 1.0
        while True:
            attempts += 1
            request = Request(url, data=body, headers=headers, method='POST')
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return self._decode_response(response.read())
            except HTTPError as exc:
                raw = exc.read() if hasattr(exc, 'read') else b''
                decoded = self._safe_decode(raw)
                if exc.code == 429:
                    retry_after = self._extract_retry_after(decoded)
                    logger.warning(
                        'telegram.rate_limited method=%s retry_after=%s attempt=%s',
                        method, retry_after, attempts,
                    )
                    if attempts > MAX_RETRIES_5XX:
                        raise TelegramClientError(
                            f'429 persistente após {attempts} tentativas: '
                            f'{decoded.get("description") or "rate limit"}',
                        ) from exc
                    time.sleep(retry_after)
                    continue
                if 500 <= exc.code < 600 and attempts <= MAX_RETRIES_5XX:
                    logger.warning(
                        'telegram.5xx method=%s code=%s attempt=%s backoff=%.1fs',
                        method, exc.code, attempts, backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                description = decoded.get('description') or f'HTTP {exc.code}'
                raise TelegramClientError(
                    f'Telegram API erro {exc.code}: {description}',
                ) from exc
            except URLError as exc:
                if attempts <= MAX_RETRIES_5XX:
                    logger.warning(
                        'telegram.urlerror method=%s reason=%s attempt=%s',
                        method, exc.reason, attempts,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise TelegramClientError(
                    f'Telegram API indisponível: {exc.reason}',
                ) from exc
            except TimeoutError as exc:
                if attempts <= MAX_RETRIES_5XX:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise TelegramClientError(
                    'Tempo esgotado ao chamar Telegram API.',
                ) from exc

    def _decode_response(self, raw_body: bytes) -> dict:
        if not raw_body:
            return {}
        try:
            decoded = json.loads(raw_body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TelegramClientError('Resposta inválida da Bot API.') from exc
        if not isinstance(decoded, dict):
            raise TelegramClientError('Resposta inesperada da Bot API.')
        if not decoded.get('ok'):
            description = decoded.get('description') or 'erro desconhecido'
            raise TelegramClientError(f'Bot API recusou: {description}')
        return decoded

    @staticmethod
    def _safe_decode(raw: bytes) -> dict:
        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _extract_retry_after(decoded: dict) -> float:
        parameters = decoded.get('parameters') or {}
        retry_after = parameters.get('retry_after')
        try:
            return max(1.0, float(retry_after))
        except (TypeError, ValueError):
            return 5.0
