from __future__ import annotations

import logging
import math
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

import requests
from django.conf import settings

from .mercadolivre_auth import (
    MercadoLivreAuthError,
    MercadoLivreTokenProvider,
    is_exact_api_base_url,
    validate_api_configuration,
)

log = logging.getLogger('apps.marketplaces.mercadolivre_api')
ML_ITEM_ID_RE = re.compile(r'^MLB[0-9]+$')
ML_SELLER_ID_RE = re.compile(r'^[0-9]+$')
MAX_RETRY_AFTER_SECONDS = 3600.0


class MercadoLivreApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        endpoint: str,
        retryable: bool = False,
        auth_error: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.retryable = retryable
        self.auth_error = auth_error


class MercadoLivreApiClient:
    """Cliente somente para a API pública api.mercadolibre.com."""

    def __init__(
        self,
        *,
        token_provider: MercadoLivreTokenProvider | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        transport=None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.token_provider = token_provider or MercadoLivreTokenProvider()
        self.base_url = (base_url or settings.ML_API_BASE_URL).rstrip('/')
        self.timeout = timeout if timeout is not None else settings.ML_API_TIMEOUT_SECONDS
        self.max_retries = max(1, max_retries if max_retries is not None else settings.ML_API_MAX_RETRIES)
        self.session = transport or requests.Session()
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()
        self._clock = clock or time.time
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}

    def get(self, path: str, *, params: dict[str, str | int] | None = None) -> Any:
        return self._request('GET', path, params=params)

    def get_items(self, item_ids: list[str]) -> list[dict]:
        if not isinstance(item_ids, list) or any(
            not isinstance(item_id, str) or not ML_ITEM_ID_RE.fullmatch(item_id)
            for item_id in item_ids
        ) or len(set(item_ids)) != len(item_ids):
            raise MercadoLivreApiError(
                'Lote de itens inválido para multiget.',
                status_code=None,
                endpoint='/items/bulk',
            )

        results: list[dict] = []
        for start in range(0, len(item_ids), 20):
            batch = item_ids[start:start + 20]
            if not batch:
                continue
            response = self.get('/items/bulk', params={'ids': ','.join(batch)})
            self._validate_bulk_response(response, batch)
            results.extend(response)
        return results

    @staticmethod
    def _validate_bulk_response(response: Any, requested_ids: list[str]) -> None:
        if not isinstance(response, list) or len(response) != len(requested_ids):
            raise MercadoLivreApiError(
                'Multiget /items/bulk retornou cardinalidade inválida.',
                status_code=None,
                endpoint='/items/bulk',
            )

        requested = set(requested_ids)
        returned: set[str] = set()
        for entry in response:
            if not isinstance(entry, dict):
                raise MercadoLivreApiError(
                    'Multiget /items/bulk retornou item inválido.',
                    status_code=None,
                    endpoint='/items/bulk',
                )
            entry_id = entry.get('id')
            status_code = entry.get('status_code')
            if (
                not isinstance(entry_id, str)
                or not ML_ITEM_ID_RE.fullmatch(entry_id)
                or entry_id not in requested
                or entry_id in returned
                or isinstance(status_code, bool)
                or not isinstance(status_code, int)
                or not (
                    status_code == 200
                    or 400 <= status_code <= 599
                )
            ):
                raise MercadoLivreApiError(
                    'Multiget /items/bulk retornou metadados inválidos.',
                    status_code=None,
                    endpoint='/items/bulk',
                )
            returned.add(entry_id)
            if status_code == 200:
                body = entry.get('body')
                body_id = body.get('id') if isinstance(body, dict) else None
                if (
                    not isinstance(body, dict)
                    or not isinstance(body_id, str)
                    or not ML_ITEM_ID_RE.fullmatch(body_id)
                    or body_id != entry_id
                ):
                    raise MercadoLivreApiError(
                        'Multiget /items/bulk retornou body inválido.',
                        status_code=None,
                        endpoint='/items/bulk',
                    )
        if returned != requested:
            raise MercadoLivreApiError(
                'Multiget /items/bulk não retornou todos os itens solicitados.',
                status_code=None,
                endpoint='/items/bulk',
            )

    def get_item(self, item_id: str) -> dict:
        self._validate_item_id(item_id, '/items/{ITEM_ID}')
        cache_key = ('item', item_id)
        cached = self._cache_get(cache_key, settings.ML_API_ITEM_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        body = self.get(f'/items/{item_id}')
        if not isinstance(body, dict):
            raise MercadoLivreApiError(
                'Detalhe de item retornou formato inválido.',
                status_code=None,
                endpoint='/items/{ITEM_ID}',
            )
        body_id = body.get('id')
        if (
            not isinstance(body_id, str)
            or not ML_ITEM_ID_RE.fullmatch(body_id)
            or body_id != item_id
        ):
            raise MercadoLivreApiError(
                'Detalhe de item retornou identificador inconsistente.',
                status_code=None,
                endpoint='/items/{ITEM_ID}',
            )
        self._cache_set(cache_key, body)
        return body

    def get_sale_price(self, item_id: str, context: str) -> dict:
        self._validate_item_id(item_id, '/items/{ITEM_ID}/sale_price')
        cache_key = ('sale_price', f'{item_id}:{context}')
        cached = self._cache_get(cache_key, settings.ML_API_ITEM_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        body = self.get(
            f'/items/{item_id}/sale_price',
            params={'context': context},
        )
        if not isinstance(body, dict):
            raise MercadoLivreApiError(
                'Preço contextual retornou formato inválido.',
                status_code=None,
                endpoint='/items/{ITEM_ID}/sale_price',
            )
        self._cache_set(cache_key, body)
        return body

    def get_seller(self, seller_id: str) -> dict:
        self._validate_seller_id(seller_id)
        cache_key = ('seller', seller_id)
        cached = self._cache_get(cache_key, settings.ML_API_SELLER_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached
        body = self.get(
            f'/users/{seller_id}',
            params={'attributes': 'seller_reputation'},
        )
        if not isinstance(body, dict):
            raise MercadoLivreApiError(
                'Dados do vendedor retornaram formato inválido.',
                status_code=None,
                endpoint='/users/{USER_ID}',
            )
        body_id = body.get('id')
        normalized_body_id = (
            str(body_id)
            if isinstance(body_id, int) and not isinstance(body_id, bool)
            else body_id
        )
        if (
            not isinstance(normalized_body_id, str)
            or not ML_SELLER_ID_RE.fullmatch(normalized_body_id)
            or normalized_body_id != seller_id
        ):
            raise MercadoLivreApiError(
                'Dados do vendedor retornaram identificador inconsistente.',
                status_code=None,
                endpoint='/users/{USER_ID}',
            )
        self._cache_set(cache_key, body)
        return body

    def _request(self, method: str, path: str, *, params: dict[str, str | int] | None = None) -> Any:
        validate_api_configuration()
        endpoint = self._safe_endpoint(path)
        refreshed = False
        last_error: MercadoLivreApiError | None = None

        for attempt in range(1, self.max_retries + 1):
            response = None
            auth_failed = False
            request_error_name: str | None = None
            external_error_name: str | None = None
            try:
                token = self.token_provider.access_token
                response = self.session.request(
                    method,
                    f'{self.base_url}{endpoint}',
                    params=params,
                    headers={
                        'Accept': 'application/json',
                        'Authorization': f'Bearer {token}',
                        'User-Agent': 'descontos.bot/mercadolivre-api',
                    },
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except MercadoLivreAuthError:
                auth_failed = True
            except requests.RequestException as exc:
                request_error_name = type(exc).__name__
                last_error = MercadoLivreApiError(
                    f'Falha de rede no endpoint {endpoint}: {request_error_name}',
                    status_code=None,
                    endpoint=endpoint,
                    retryable=True,
                )
            except Exception as exc:  # noqa: BLE001 - fronteira externa fail-closed
                external_error_name = type(exc).__name__

            if auth_failed:
                raise MercadoLivreApiError(
                    'Autenticação do Mercado Livre falhou.',
                    status_code=401,
                    endpoint=endpoint,
                    auth_error=True,
                )
            if external_error_name is not None:
                raise MercadoLivreApiError(
                    f'Falha externa no endpoint {endpoint}: {external_error_name}.',
                    status_code=None,
                    endpoint=endpoint,
                )
            if request_error_name is not None:
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error or MercadoLivreApiError(
                    'Falha de rede não classificada.',
                    status_code=None,
                    endpoint=endpoint,
                )
            if response is None:
                raise MercadoLivreApiError(
                    'O Mercado Livre não retornou uma resposta HTTP.',
                    status_code=None,
                    endpoint=endpoint,
                )

            status = None
            status_error_name = None
            try:
                raw_status = getattr(response, 'status_code', 0)
                if type(raw_status) is not int or not 100 <= raw_status <= 599:
                    status_error_name = 'invalid_status'
                else:
                    status = raw_status
            except Exception as exc:  # noqa: BLE001 - resposta externa fail-closed
                status_error_name = type(exc).__name__
            if status_error_name is not None or status is None:
                raise MercadoLivreApiError(
                    'Resposta HTTP inválida do Mercado Livre.',
                    status_code=None,
                    endpoint=endpoint,
                )
            if status == 401:
                if not refreshed:
                    refreshed = True
                    refresh_failed = False
                    try:
                        self.token_provider.refresh()
                    except Exception:  # noqa: BLE001 - refresh externo fail-closed
                        refresh_failed = True
                    if refresh_failed:
                        raise MercadoLivreApiError(
                            'Token do Mercado Livre rejeitado e refresh indisponível.',
                            status_code=401,
                            endpoint=endpoint,
                            auth_error=True,
                        )
                    if attempt < self.max_retries:
                        continue
                raise MercadoLivreApiError(
                    'Token do Mercado Livre rejeitado após refresh.',
                    status_code=401,
                    endpoint=endpoint,
                    auth_error=True,
                )

            if status == 429:
                last_error = MercadoLivreApiError(
                    'Rate limit do Mercado Livre excedido.',
                    status_code=429,
                    endpoint=endpoint,
                    retryable=True,
                )
                if attempt < self.max_retries:
                    self._sleep_retry_after(response, attempt)
                    continue
                raise last_error

            if status >= 500:
                last_error = MercadoLivreApiError(
                    f'Falha transitória do Mercado Livre (HTTP {status}).',
                    status_code=status,
                    endpoint=endpoint,
                    retryable=True,
                )
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error

            if status in (400, 403, 404):
                raise MercadoLivreApiError(
                    f'Mercado Livre rejeitou {endpoint} (HTTP {status}).',
                    status_code=status,
                    endpoint=endpoint,
                    auth_error=status == 403,
                )

            if status < 200 or status >= 300:
                raise MercadoLivreApiError(
                    f'Mercado Livre respondeu HTTP {status}.',
                    status_code=status,
                    endpoint=endpoint,
                )

            json_invalid = False
            body = None
            try:
                body = response.json()
            except Exception:  # noqa: BLE001 - resposta externa não deve vazar causa
                json_invalid = True
            if json_invalid:
                raise MercadoLivreApiError(
                    f'Resposta JSON inválida em {endpoint}.',
                    status_code=status,
                    endpoint=endpoint,
                )
            return body

        raise last_error or MercadoLivreApiError(
            'Falha HTTP não classificada.',
            status_code=None,
            endpoint=endpoint,
        )

    def _safe_endpoint(self, path: str) -> str:
        if (
            not isinstance(path, str)
            or not path.startswith('/')
            or '://' in path
            or '?' in path
            or '#' in path
            or '\\' in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise MercadoLivreApiError(
                'Endpoint inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint='invalid',
            )
        parsed_path = None
        parse_error = False
        try:
            parsed_path = urlsplit(path)
        except ValueError:
            parse_error = True
        if parse_error or parsed_path is None:
            raise MercadoLivreApiError(
                'Endpoint inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint='invalid',
            )
        decoded_path = parsed_path.path
        for _ in range(5):
            unquoted_path = unquote(decoded_path)
            if unquoted_path == decoded_path:
                break
            decoded_path = unquoted_path
        else:
            decoded_path = ''
        decoded_parts = urlsplit(decoded_path)
        encoded_separator = decoded_path.count('/') != parsed_path.path.count('/')
        if (
            not decoded_path
            or encoded_separator
            or '\\' in decoded_path
            or '?' in decoded_path
            or '#' in decoded_path
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
            or decoded_parts.scheme
            or decoded_parts.netloc
            or decoded_parts.query
            or decoded_parts.fragment
            or any(segment in {'.', '..'} for segment in decoded_parts.path.split('/'))
        ):
            raise MercadoLivreApiError(
                'Endpoint inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint='invalid',
            )
        if parsed_path.scheme or parsed_path.netloc or parsed_path.query or parsed_path.fragment:
            raise MercadoLivreApiError(
                'Endpoint inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint='invalid',
            )
        if not is_exact_api_base_url(self.base_url):
            raise MercadoLivreApiError(
                'Base da API pública do Mercado Livre não permitida.',
                status_code=None,
                endpoint='invalid',
            )
        return parsed_path.path

    @staticmethod
    def _validate_item_id(item_id: str, endpoint: str) -> None:
        if not isinstance(item_id, str) or not ML_ITEM_ID_RE.fullmatch(item_id):
            raise MercadoLivreApiError(
                'Identificador de item inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint=endpoint,
            )

    @staticmethod
    def _validate_seller_id(seller_id: str) -> None:
        if not isinstance(seller_id, str) or not ML_SELLER_ID_RE.fullmatch(seller_id):
            raise MercadoLivreApiError(
                'Identificador de vendedor inválido para API pública do Mercado Livre.',
                status_code=None,
                endpoint='/users/{USER_ID}',
            )

    def _sleep_backoff(self, attempt: int) -> None:
        base = min(2 ** (attempt - 1), 8)
        self._sleep(base + self._rng.uniform(0, 0.5))

    def _sleep_retry_after(self, response, attempt: int) -> None:
        try:
            raw = str(getattr(response, 'headers', {}).get('Retry-After', '') or '').strip()
        except Exception:  # noqa: BLE001 - header externo inválido
            raw = ''
        delay: float | None = None
        if raw.isascii() and raw.isdigit():
            try:
                candidate = float(raw)
            except (TypeError, ValueError, OverflowError):
                candidate = None
            if candidate is not None and math.isfinite(candidate) and candidate <= MAX_RETRY_AFTER_SECONDS:
                delay = candidate
        elif raw:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                candidate = retry_at.timestamp() - self._clock()
                if math.isfinite(candidate) and 0.0 <= candidate <= MAX_RETRY_AFTER_SECONDS:
                    delay = candidate
            except (TypeError, ValueError, OverflowError):
                delay = None
        self._sleep(delay if delay is not None else min(2 ** (attempt - 1), 8))

    def _cache_get(self, key: tuple[str, str], ttl: int) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: tuple[str, str], value: Any) -> None:
        ttl = settings.ML_API_ITEM_CACHE_TTL_SECONDS
        if key[0] == 'seller':
            ttl = settings.ML_API_SELLER_CACHE_TTL_SECONDS
        self._cache[key] = (self._clock() + ttl, value)
