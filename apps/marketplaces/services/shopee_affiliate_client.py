"""Cliente da Shopee Affiliate Open API (GraphQL).

Encapsula serialização estável do payload, assinatura SHA256, header de
autorização, retry com backoff e tratamento de erro — sem vazar o secret em log.

Assinatura oficial:
    Authorization: SHA256 Credential={AppId}, Timestamp={ts}, Signature={sig}
    sig = SHA256(AppId + Timestamp + Payload + Secret)

`Payload` precisa ser exatamente o corpo JSON enviado, por isso a serialização é
determinística (mesma string assinada e enviada).
"""

import hashlib
import json
import logging
import time

from django.conf import settings

log = logging.getLogger('apps.marketplaces.shopee')


class ShopeeAffiliateError(RuntimeError):
    """Erro controlado de chamada à Shopee Affiliate API."""


class ShopeeConfigError(ShopeeAffiliateError):
    """Credenciais/config ausentes ou conector desabilitado."""


def serialize_payload(query: str, variables: dict | None) -> str:
    """Serializa o corpo GraphQL de forma estável (mesma string assina e envia)."""
    return json.dumps(
        {'query': query, 'variables': variables or {}},
        separators=(',', ':'),
        ensure_ascii=False,
        sort_keys=True,
    )


def build_signature(app_id: str, timestamp: int, payload: str, secret: str) -> str:
    base = f'{app_id}{timestamp}{payload}{secret}'
    return hashlib.sha256(base.encode('utf-8')).hexdigest()


def build_auth_header(app_id: str, timestamp: int, signature: str) -> str:
    return f'SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}'


def _default_transport(url, data, headers, timeout):
    # Import tardio para manter o módulo importável em testes sem rede.
    import requests

    return requests.post(url, data=data, headers=headers, timeout=timeout)


class ShopeeAffiliateClient:
    def __init__(
        self,
        app_id: str | None = None,
        secret: str | None = None,
        api_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        transport=None,
        clock=None,
        sleep=None,
    ):
        self.app_id = app_id if app_id is not None else settings.SHOPEE_AFFILIATE_APP_ID
        self.secret = secret if secret is not None else settings.SHOPEE_AFFILIATE_SECRET
        self.api_url = api_url or settings.SHOPEE_AFFILIATE_API_URL
        self.timeout = timeout if timeout is not None else settings.SHOPEE_AFFILIATE_TIMEOUT_SECONDS
        self.max_retries = (
            max_retries if max_retries is not None else settings.SHOPEE_AFFILIATE_MAX_RETRIES
        )
        self._transport = transport or _default_transport
        self._clock = clock or (lambda: int(time.time()))
        self._sleep = sleep or time.sleep

    def execute(self, query: str, variables: dict | None = None) -> dict:
        if not self.app_id or not self.secret:
            raise ShopeeConfigError(
                'Credenciais Shopee ausentes (SHOPEE_AFFILIATE_APP_ID/SECRET).',
            )

        payload = serialize_payload(query, variables)
        timestamp = self._clock()
        signature = build_signature(self.app_id, timestamp, payload, self.secret)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': build_auth_header(self.app_id, timestamp, signature),
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._transport(
                    self.api_url,
                    payload.encode('utf-8'),
                    headers,
                    self.timeout,
                )
                return self._handle_response(response)
            except ShopeeAffiliateError:
                # Erro de aplicação (GraphQL/config): não adianta repetir.
                raise
            except Exception as exc:  # noqa: BLE001 — rede/timeout: candidato a retry.
                last_error = exc
                log.warning(
                    'shopee_request_retry attempt=%s/%s error=%s',
                    attempt,
                    self.max_retries,
                    type(exc).__name__,
                )
                if attempt < self.max_retries:
                    self._sleep(min(2 ** (attempt - 1), 8))

        raise ShopeeAffiliateError(
            f'Falha ao chamar a Shopee após {self.max_retries} tentativas: '
            f'{type(last_error).__name__}',
        )

    def _handle_response(self, response) -> dict:
        status = getattr(response, 'status_code', None)
        if status is not None and status >= 500:
            # Transitório: deixa o loop de retry tratar.
            raise ConnectionError(f'Shopee HTTP {status}')
        if status is not None and status >= 400:
            raise ShopeeAffiliateError(f'Shopee respondeu HTTP {status}.')

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ShopeeAffiliateError('Resposta Shopee não é JSON válido.') from exc

        errors = body.get('errors') if isinstance(body, dict) else None
        if errors:
            # Mensagens de erro da Shopee não trazem secret; seguro logar resumo.
            log.error('shopee_graphql_errors count=%s', len(errors))
            raise ShopeeAffiliateError(f'Shopee retornou erros GraphQL: {errors}')

        data = body.get('data') if isinstance(body, dict) else None
        if data is None:
            raise ShopeeAffiliateError('Resposta Shopee sem campo data.')
        return data
