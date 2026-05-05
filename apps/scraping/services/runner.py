import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import OfferNormalizationError, normalize_offer
from apps.offers.services.repository import save_normalized_offer
from apps.scraping.models import ScrapingRun
from apps.scraping.services.adapters import build_adapter


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScrapingResult:
    run: ScrapingRun
    total_collected: int
    total_valid: int
    total_created: int
    total_updated: int


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
    except Exception as exc:
        log.exception('Falha ao coletar marketplace %s.', marketplace.code)
        _finish_run(
            run=run,
            status=ScrapingRun.RunStatus.FAILED,
            total_collected=0,
            total_valid=0,
            error_message=str(exc),
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
