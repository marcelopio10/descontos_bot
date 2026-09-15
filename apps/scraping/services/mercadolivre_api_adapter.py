from __future__ import annotations

import os

from apps.analytics.services.alertas import enviar_alerta_operador
from apps.marketplaces.services.mercadolivre_affiliate_adapter import ExistingAffiliateLinkEngineAdapter
from apps.marketplaces.services.mercadolivre_auth import (
    MercadoLivreAuthError,
    validate_api_configuration,
)
from apps.marketplaces.services.mercadolivre_api_pipeline import MercadoLivreApiPipeline


def _affiliate_alert(reason: str) -> None:
    enviar_alerta_operador(
        'Cookie/token do Mercado Livre expirou, foi rejeitado ou está ausente '
        f'(motivo: {reason}). Renove ML_COOKIE e ML_CSRF_TOKEN no .env.',
        categoria='ml_cookie_expirado',
    )


class MercadoLivreApiAdapter:
    provider_name = 'mercadolivre_api'
    blocked = False
    error_message = ''
    pages_scraped = 0

    def __init__(self, *, pipeline_factory=None) -> None:
        self._pipeline_factory = pipeline_factory

    def run(self, *, marketplace, run, max_pages: int):
        from apps.scraping.services.adapters import _mercadolivre_api_search_enabled

        invalid_flag = False
        try:
            enabled = _mercadolivre_api_search_enabled()
        except ValueError:
            invalid_flag = True
            enabled = False
        if invalid_flag:
            raise MercadoLivreAuthError('MERCADOLIVRE_API_SEARCH_ENABLED inválida.')
        if not enabled:
            raise MercadoLivreAuthError('Busca pela API ML está desabilitada.')
        validate_api_configuration()
        affiliate_adapter = ExistingAffiliateLinkEngineAdapter(
            affiliate_tag=os.environ.get('ML_AFFILIATE_TAG', ''),
            ml_cookie=os.environ.get('ML_COOKIE', ''),
            ml_csrf=os.environ.get('ML_CSRF_TOKEN', ''),
            alert_callback=_affiliate_alert,
        )
        pipeline_error_name = None
        pipeline = None
        result = None
        try:
            if self._pipeline_factory:
                pipeline = self._pipeline_factory(
                    marketplace=marketplace,
                    run=run,
                    max_pages=max_pages,
                    affiliate_adapter=affiliate_adapter,
                )
            else:
                pipeline = MercadoLivreApiPipeline(
                    marketplace=marketplace,
                    run=run,
                    max_pages=max_pages,
                    affiliate_adapter=affiliate_adapter,
                )
            result = pipeline.run_collection()
        except Exception as exc:  # noqa: BLE001 - pipeline externo fail-closed
            pipeline_error_name = type(exc).__name__
        if pipeline_error_name is not None:
            raise MercadoLivreAuthError(
                f'Provider API ML falhou ({pipeline_error_name}).',
            )
        assert result is not None
        self.pages_scraped = result.total_collected
        self.error_message = ' | '.join(result.errors[:5])
        return result
