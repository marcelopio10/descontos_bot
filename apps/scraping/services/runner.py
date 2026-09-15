import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.analytics.services.alertas import alertar_scraper_zero_ofertas
from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import OfferNormalizationError, normalize_offer
from apps.offers.services.repository import save_normalized_offer
from apps.scraping.models import ScrapingItemResult, ScrapingRun
from apps.scraping.services.adapters import build_adapter


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScrapingResult:
    run: ScrapingRun
    total_collected: int
    total_valid: int
    total_created: int
    total_updated: int
    total_discarded: int = 0


def run_marketplace_scraping(marketplace: Marketplace, max_pages: int) -> ScrapingResult:
    run = ScrapingRun.objects.create(
        marketplace=marketplace,
        started_at=timezone.now(),
        status=ScrapingRun.RunStatus.RUNNING,
    )

    total_valid = 0
    total_created = 0
    total_updated = 0
    errors: list[str] = []

    try:
        adapter = build_adapter(marketplace.code)
        provider = str(getattr(adapter, 'provider_name', 'legacy_scraper'))
        run.provider = provider
        run.save(update_fields=['provider', 'updated_at'])

        if hasattr(adapter, 'run'):
            try:
                api_result = adapter.run(
                    marketplace=marketplace,
                    run=run,
                    max_pages=max_pages,
                )
                api_errors = list(api_result.errors)
                if api_result.total_valid == 0:
                    api_errors.append(
                        'Nenhuma oferta válida no provider API; revisar elegibilidade e configuração.'
                    )
                status = ScrapingRun.RunStatus.SUCCESS
                if api_errors:
                    status = (
                        ScrapingRun.RunStatus.PARTIAL_FAILED
                        if api_result.total_valid
                        else ScrapingRun.RunStatus.FAILED
                    )
                _finish_run(
                    run=run,
                    status=status,
                    total_collected=api_result.total_collected,
                    total_valid=api_result.total_valid,
                    error_message=' | '.join(api_errors[:5]),
                )
                if status == ScrapingRun.RunStatus.FAILED:
                    alertar_scraper_zero_ofertas(
                        marketplace_code=marketplace.code,
                        run_id=run.id,
                        detalhe=' | '.join(api_errors[:3]) or 'Falha no provider API.',
                    )
                return ScrapingResult(
                    run=run,
                    total_collected=api_result.total_collected,
                    total_valid=api_result.total_valid,
                    total_created=api_result.total_created,
                    total_updated=api_result.total_updated,
                    total_discarded=api_result.total_discarded,
                )
            except Exception as exc:
                log.exception('Falha no provider API do marketplace %s.', marketplace.code)
                collected = run.item_results.count()
                valid = run.item_results.filter(
                    status__in=(
                        ScrapingItemResult.Status.ACCEPTED,
                        ScrapingItemResult.Status.AFFILIATE_FAILED,
                    ),
                ).count()
                discarded = run.item_results.filter(
                    status=ScrapingItemResult.Status.DISCARDED,
                ).count()
                _finish_run(
                    run=run,
                    status=ScrapingRun.RunStatus.FAILED,
                    total_collected=collected,
                    total_valid=valid,
                    error_message=str(exc),
                )
                alertar_scraper_zero_ofertas(
                    marketplace_code=marketplace.code,
                    run_id=run.id,
                    detalhe=f'Exceção durante provider API: {exc}',
                )
                return ScrapingResult(
                    run=run,
                    total_collected=collected,
                    total_valid=valid,
                    total_created=0,
                    total_updated=0,
                    total_discarded=discarded,
                )

        payloads = adapter.collect(max_pages=max_pages)

        for payload in payloads:
            try:
                normalized_offer = normalize_offer(marketplace, payload)
            except OfferNormalizationError as exc:
                errors.append(str(exc))
                if marketplace.code == 'amazon' and 'ASIN não encontrado' in str(exc):
                    log.warning('%s', exc)
                else:
                    log.debug('Oferta ignorada em %s: %s', marketplace.code, exc)
                continue

            with transaction.atomic():
                _, created = save_normalized_offer(normalized_offer)
            total_valid += 1
            if created:
                total_created += 1
            else:
                total_updated += 1

        if adapter.blocked:
            errors.append(adapter.error_message or 'CAPTCHA ou HTML bloqueado detectado.')
        if total_valid == 0 and not adapter.blocked:
            zero_offers_message = (
                f'{marketplace.name} retornou 0 ofertas válidas; '
                'verificar seletor, bloqueio silencioso ou execução do marketplace.'
            )
            errors.append(zero_offers_message)
            log.error(
                'scraping.zero_valid_offers marketplace=%s run_id=%s collected=%s',
                marketplace.code, run.id, len(payloads),
            )

        status = ScrapingRun.RunStatus.SUCCESS
        if errors or adapter.blocked:
            status = ScrapingRun.RunStatus.PARTIAL_FAILED if total_valid else ScrapingRun.RunStatus.FAILED

        _finish_run(
            run=run,
            status=status,
            total_collected=len(payloads),
            total_valid=total_valid,
            error_message=' | '.join(errors[:5]),
        )

        if status == ScrapingRun.RunStatus.FAILED:
            alertar_scraper_zero_ofertas(
                marketplace_code=marketplace.code,
                run_id=run.id,
                detalhe=' | '.join(errors[:3]),
            )
    except Exception as exc:
        log.exception('Falha ao coletar marketplace %s.', marketplace.code)
        _finish_run(
            run=run,
            status=ScrapingRun.RunStatus.FAILED,
            total_collected=0,
            total_valid=0,
            error_message=str(exc),
        )
        alertar_scraper_zero_ofertas(
            marketplace_code=marketplace.code,
            run_id=run.id,
            detalhe=f'Exceção durante a coleta: {exc}',
        )

    return ScrapingResult(
        run=run,
        total_collected=run.total_collected,
        total_valid=run.total_valid,
        total_created=total_created,
        total_updated=total_updated,
    )


def _finish_run(
    run: ScrapingRun,
    status: str,
    total_collected: int,
    total_valid: int,
    error_message: str,
) -> None:
    run.status = status
    run.total_collected = total_collected
    run.total_valid = total_valid
    run.error_message = error_message[:2000]
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            'status',
            'total_collected',
            'total_valid',
            'error_message',
            'finished_at',
            'updated_at',
        ],
    )
