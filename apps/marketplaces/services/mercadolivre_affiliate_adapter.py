from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Any
from urllib.parse import unquote, urlsplit

from apps.offers.services.normalizer import is_canonical_mercadolivre_product_path
from scrapers.base import build_impersonated_session

log = logging.getLogger('apps.marketplaces.mercadolivre_affiliate')
ALLOWED_SHORT_URL_HOSTS = frozenset({
    'mercadolivre.com',
    'mercadolivre.com.br',
    'www.mercadolivre.com',
    'www.mercadolivre.com.br',
})
ALLOWED_PRODUCT_URL_HOSTS = frozenset({
    'mercadolivre.com.br',
    'www.mercadolivre.com.br',
    'produto.mercadolivre.com.br',
})
SHORT_SLUG_RE = re.compile(r'/sec/[A-Za-z0-9._~-]+')



@dataclass(frozen=True)
class AffiliateLinkResult:
    url: str
    generated: bool
    error_code: str = ''


class ExistingAffiliateLinkEngineAdapter:
    """Adapter fino sobre o motor legado de afiliados do Mercado Livre."""

    endpoint = 'https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links'

    def __init__(
        self,
        *,
        affiliate_tag: str = '',
        ml_cookie: str = '',
        ml_csrf: str = '',
        session_factory: Callable[[], Any] | None = None,
        alert_callback: Callable[..., None] | None = None,
    ) -> None:
        self.affiliate_tag = str(affiliate_tag or '').strip()
        self.ml_cookie = str(ml_cookie or '').strip()
        self.ml_csrf = str(ml_csrf or '').strip()
        self._session_factory = session_factory or (lambda: build_impersonated_session('chrome124'))
        self._alert_callback = alert_callback
        self._alert_shown = False

    def generate_result(self, original_url: str) -> AffiliateLinkResult:
        if not isinstance(original_url, str):
            return AffiliateLinkResult('', False, 'empty_original_url')
        if any(ord(char) < 32 or ord(char) == 127 for char in original_url):
            return AffiliateLinkResult('', False, 'original_url_invalid')
        original_url = original_url.strip()
        if not original_url:
            return AffiliateLinkResult('', False, 'empty_original_url')
        if not self._is_allowed_product_url(original_url):
            return AffiliateLinkResult('', False, 'original_url_invalid')
        if not self.ml_cookie or not self.ml_csrf or not self.affiliate_tag:
            self._alert('credentials_missing')
            return AffiliateLinkResult(original_url, False, 'credentials_missing')

        try:
            response = self._session_factory().post(
                self.endpoint,
                headers={
                    'accept': 'application/json, text/plain, */*',
                    'content-type': 'application/json',
                    'cookie': self.ml_cookie,
                    'origin': 'https://www.mercadolivre.com.br',
                    'referer': original_url,
                    'user-agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/147.0.0.0 Safari/537.36'
                    ),
                    'x-csrf-token': self.ml_csrf,
                },
                json={'url': original_url, 'tag': self.affiliate_tag},
                timeout=10,
                allow_redirects=False,
            )
            raw_status = getattr(response, 'status_code', None)
            if type(raw_status) is not int or not 100 <= raw_status <= 599:
                return AffiliateLinkResult(original_url, False, 'affiliate_response_invalid')
            status = raw_status
            if 200 <= status < 300:
                body = response.json()
                raw_short_url = body.get('short_url') if isinstance(body, dict) else None
                if not isinstance(raw_short_url, str) or not raw_short_url:
                    return AffiliateLinkResult(original_url, False, 'affiliate_url_missing')
                if any(ord(char) < 32 or ord(char) == 127 for char in raw_short_url):
                    return AffiliateLinkResult(original_url, False, 'affiliate_url_missing')
                short_url = raw_short_url.strip()
                if not short_url:
                    return AffiliateLinkResult(original_url, False, 'affiliate_url_missing')
                if short_url and self._is_allowed_short_url(short_url):
                    if short_url == original_url:
                        return AffiliateLinkResult(original_url, False, 'affiliate_same_as_original')
                    return AffiliateLinkResult(short_url, True)
                return AffiliateLinkResult(original_url, False, 'affiliate_url_missing')
            if status in (401, 403):
                self._alert(f'rejected_http_{status}')
            else:
                log.error('Motor afiliado do ML respondeu HTTP %s.', status)
            return AffiliateLinkResult(original_url, False, f'http_{status}')
        except Exception as exc:  # noqa: BLE001 - preserva fallback legado
            log.error('Erro no motor afiliado do ML: %s', type(exc).__name__)
            return AffiliateLinkResult(original_url, False, 'affiliate_request_failed')

    def generate(self, original_url: str) -> str:
        return self.generate_result(original_url).url

    def _alert(self, reason: str) -> None:
        if self._alert_shown:
            return
        self._alert_shown = True
        message = (
            'Credenciais do motor afiliado do Mercado Livre estão ausentes ou foram '
            f'rejeitadas (motivo: {reason}). Renove ML_AFFILIATE_TAG, ML_COOKIE e '
            'ML_CSRF_TOKEN no .env.'
        )
        log.error('ATENÇÃO: %s', message)
        if self._alert_callback:
            try:
                self._alert_callback(reason)
            except Exception as exc:  # noqa: BLE001 - alerta não bloqueia fallback
                log.error('Callback de alerta do afiliado falhou: %s', type(exc).__name__)

    @staticmethod
    def _is_allowed_short_url(value: str) -> bool:
        try:
            parts = urlsplit(value)
            port = parts.port
        except (TypeError, ValueError):
            return False
        decoded_path = _decode_path(parts.path)
        return (
            not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and decoded_path is not None
            and decoded_path == parts.path
            and not any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
            and parts.scheme == 'https'
            and parts.hostname is not None
            and parts.hostname.lower() in ALLOWED_SHORT_URL_HOSTS
            and port is None
            and parts.username is None
            and parts.password is None
            and SHORT_SLUG_RE.fullmatch(decoded_path) is not None
            and decoded_path[5:] not in {'.', '..'}
            and '?' not in value
            and '#' not in value
            and not parts.query
            and not parts.fragment
        )

    @staticmethod
    def _is_allowed_product_url(value: str) -> bool:
        try:
            parts = urlsplit(value)
            port = parts.port
        except (TypeError, ValueError):
            return False
        decoded_path = _decode_path(parts.path)
        return (
            not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and decoded_path is not None
            and not any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
            and parts.scheme == 'https'
            and parts.hostname is not None
            and parts.hostname.lower() in ALLOWED_PRODUCT_URL_HOSTS
            and port is None
            and parts.username is None
            and parts.password is None
            and is_canonical_mercadolivre_product_path(decoded_path)
            and decoded_path == parts.path
            and '?' not in value
            and '#' not in value
            and '\\' not in decoded_path
            and not any(segment in {'.', '..'} for segment in decoded_path.split('/'))
            and not parts.query
            and not parts.fragment
            and '#' not in value
        )


def _decode_path(path: str) -> str | None:
    decoded = path
    for _ in range(5):
        unquoted = unquote(decoded)
        if unquoted == decoded:
            return decoded
        decoded = unquoted
    return None
