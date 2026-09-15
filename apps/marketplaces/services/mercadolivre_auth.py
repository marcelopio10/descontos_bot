from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from django.conf import settings


class MercadoLivreAuthError(RuntimeError):
    """Falha segura durante leitura ou refresh do token OAuth do Mercado Livre."""

    def __init__(self, message: str, *, code: str = '', missing_fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.missing_fields = missing_fields


@dataclass(frozen=True, repr=False)
class TokenSnapshot:
    access_token: str
    refresh_token: str = ''

    def __repr__(self) -> str:
        return 'TokenSnapshot(access_token=<redacted>, refresh_token=<redacted>)'


def is_exact_api_base_url(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == 'https'
        and parsed.hostname == 'api.mercadolibre.com'
        and port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ('', '/')
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and '?' not in value
        and '#' not in value
    )


def validate_api_configuration() -> None:
    """Valida a configuração efetiva sem expor valores sensíveis."""
    validate_api_origin_configuration()
    required = (
        ('ML_API_ACCESS_TOKEN', settings.ML_API_ACCESS_TOKEN),
        ('ML_API_CLIENT_ID', settings.ML_API_CLIENT_ID),
        ('ML_API_CLIENT_SECRET', settings.ML_API_CLIENT_SECRET),
        ('ML_API_REFRESH_TOKEN', settings.ML_API_REFRESH_TOKEN),
    )
    missing = [
        name for name, value in required
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise MercadoLivreAuthError(
            f'Configuração da API ML incompleta: {", ".join(missing)}.',
            code='configuration_incomplete',
            missing_fields=tuple(missing),
        )


def validate_api_origin_configuration() -> None:
    """Valida somente origem e site, inclusive durante bootstrap de refresh."""
    origin_fields = (
        ('ML_API_BASE_URL', settings.ML_API_BASE_URL),
        ('ML_API_SITE_ID', settings.ML_API_SITE_ID),
    )
    missing = [
        name for name, value in origin_fields
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise MercadoLivreAuthError(
            f'Configuração da API ML incompleta: {", ".join(missing)}.',
            code='configuration_incomplete',
            missing_fields=tuple(missing),
        )
    if not isinstance(settings.ML_API_SITE_ID, str) or settings.ML_API_SITE_ID.strip().upper() != 'MLB':
        raise MercadoLivreAuthError('ML_API_SITE_ID não suportado; use MLB.', code='configuration_invalid')

    if not is_exact_api_base_url(settings.ML_API_BASE_URL):
        raise MercadoLivreAuthError(
            'ML_API_BASE_URL deve apontar para https://api.mercadolibre.com.',
            code='configuration_invalid',
        )


class MercadoLivreTokenProvider:
    """Mantém tokens em memória e nunca os inclui em mensagens de erro."""

    def __init__(
        self,
        *,
        access_token: object | None = None,
        refresh_token: object | None = None,
        client_id: object | None = None,
        client_secret: object | None = None,
        redirect_uri: object | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self._access_token = access_token if access_token is not None else settings.ML_API_ACCESS_TOKEN
        self._refresh_token = refresh_token if refresh_token is not None else settings.ML_API_REFRESH_TOKEN
        self._client_id = client_id if client_id is not None else settings.ML_API_CLIENT_ID
        self._client_secret = client_secret if client_secret is not None else settings.ML_API_CLIENT_SECRET
        self._redirect_uri = redirect_uri if redirect_uri is not None else settings.ML_API_REDIRECT_URI
        self._transport = transport or requests.post

    @property
    def access_token(self) -> str:
        return self._require_text(
            self._access_token,
            'ML_API_ACCESS_TOKEN',
        )

    def snapshot(self) -> TokenSnapshot:
        access_token = self._require_text(
            self._access_token,
            'ML_API_ACCESS_TOKEN',
            required=False,
        )
        refresh_token = self._require_text(
            self._refresh_token,
            'ML_API_REFRESH_TOKEN',
            required=False,
        )
        return TokenSnapshot(access_token, refresh_token)

    def refresh(self) -> str:
        validate_api_origin_configuration()
        self._require_text(
            self._access_token,
            'ML_API_ACCESS_TOKEN',
            required=False,
        )
        refresh_token = self._require_text(
            self._refresh_token,
            'ML_API_REFRESH_TOKEN',
        )
        client_id = self._require_text(self._client_id, 'ML_API_CLIENT_ID')
        client_secret = self._require_text(self._client_secret, 'ML_API_CLIENT_SECRET')
        self._require_text(
            self._redirect_uri,
            'ML_API_REDIRECT_URI',
            required=False,
        )

        response = None
        transport_error_name = None
        try:
            response = self._transport(
                'https://api.mercadolibre.com/oauth/token',
                data={
                    'grant_type': 'refresh_token',
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'refresh_token': refresh_token,
                },
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                timeout=settings.ML_API_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except Exception as exc:  # noqa: BLE001 - fronteira externa fail-closed
            transport_error_name = type(exc).__name__
        if transport_error_name is not None:
            raise MercadoLivreAuthError(f'Refresh OAuth falhou ({transport_error_name}).')
        if response is None:
            raise MercadoLivreAuthError('Refresh OAuth não retornou resposta.')
        status = None
        status_error_name = None
        try:
            status = getattr(response, 'status_code', None)
        except Exception as exc:  # noqa: BLE001 - resposta externa fail-closed
            status_error_name = type(exc).__name__
        if status_error_name is not None:
            raise MercadoLivreAuthError(
                f'Refresh OAuth falhou ao ler resposta ({status_error_name}).',
            )
        if type(status) is not int or not 100 <= status <= 599:
            raise MercadoLivreAuthError('Refresh OAuth retornou status HTTP inválido.')
        if status < 200 or status >= 300:
            raise MercadoLivreAuthError(f'Refresh OAuth rejeitado pelo Mercado Livre (HTTP {status}).')

        body = None
        json_invalid = False
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - resposta externa não deve vazar causa
            json_invalid = True
        if json_invalid:
            raise MercadoLivreAuthError('Refresh OAuth retornou JSON inválido.')

        if not isinstance(body, dict):
            raise MercadoLivreAuthError('Refresh OAuth retornou formato inválido.')
        parse_error = False
        raw_access_token = None
        raw_refresh_token = None
        has_refresh_token = False
        try:
            raw_access_token = body.get('access_token')
            has_refresh_token = 'refresh_token' in body
            if has_refresh_token:
                raw_refresh_token = body.get('refresh_token')
        except Exception:  # noqa: BLE001 - JSON externo fail-closed
            parse_error = True
        if parse_error:
            raise MercadoLivreAuthError('Refresh OAuth retornou formato inválido.')
        if not isinstance(raw_access_token, str) or not raw_access_token.strip():
            raise MercadoLivreAuthError('Refresh OAuth não retornou access_token.')
        new_access_token = raw_access_token.strip()
        new_refresh_token = None
        if has_refresh_token:
            if not isinstance(raw_refresh_token, str) or not raw_refresh_token.strip():
                raise MercadoLivreAuthError('Refresh OAuth retornou refresh_token inválido.')
            new_refresh_token = raw_refresh_token.strip()
        self._access_token = new_access_token
        if new_refresh_token is not None:
            self._refresh_token = new_refresh_token
        return new_access_token

    @staticmethod
    def _require_text(
        value: object,
        field_name: str,
        *,
        required: bool = True,
    ) -> str:
        if not isinstance(value, str):
            raise MercadoLivreAuthError(
                f'{field_name} deve ser texto.',
                code='configuration_invalid',
            )
        normalized = value.strip()
        if required and not normalized:
            raise MercadoLivreAuthError(
                f'{field_name} ausente.',
                code='configuration_incomplete',
                missing_fields=(field_name,),
            )
        return normalized
