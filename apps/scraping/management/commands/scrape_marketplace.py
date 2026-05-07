import logging

from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.models import Marketplace
from apps.orchestration.services.offer_publication import (
    get_auto_publish_skip_reason,
    publish_offers_after_capture,
)
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping


log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Coleta ofertas de um marketplace e salva no banco local.'

    def add_arguments(self, parser):
        parser.add_argument(
            'marketplace',
            choices=['mercadolivre', 'amazon', 'all'],
            help='Marketplace a coletar.',
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=5,
            help='Quantidade máxima de páginas por marketplace.',
        )

    def handle(self, *args, **options):
        max_pages = options['max_pages']
        if max_pages < 1 or max_pages > 5:
            raise CommandError('--max-pages deve ficar entre 1 e 5.')

        marketplace_code = options['marketplace']
        marketplaces = self._get_marketplaces(marketplace_code)
        has_failure = False
        summary = {
            'total_collected': 0,
            'total_valid': 0,
            'total_created': 0,
            'total_updated': 0,
        }

        self.stdout.write('Início da captura de ofertas nos marketplaces.')
        log.info('Captura manual iniciada. marketplace=%s max_pages=%s', marketplace_code, max_pages)
        for marketplace in marketplaces:
            self.stdout.write(f'Coletando ofertas de {marketplace.name}...')
            result = run_marketplace_scraping(marketplace=marketplace, max_pages=max_pages)
            run = result.run
            summary['total_collected'] += result.total_collected
            summary['total_valid'] += result.total_valid
            summary['total_created'] += result.total_created
            summary['total_updated'] += result.total_updated

            if run.status in (ScrapingRun.RunStatus.FAILED, ScrapingRun.RunStatus.PARTIAL_FAILED):
                has_failure = True

            self.stdout.write(
                self.style.SUCCESS(
                    (
                        f'{marketplace.name}: {run.status}; '
                        f'coletadas={result.total_collected}; '
                        f'válidas={result.total_valid}; '
                        f'criadas={result.total_created}; '
                        f'atualizadas={result.total_updated}'
                    ),
                ),
            )
            if run.error_message:
                self.stdout.write(self.style.WARNING(f'Aviso: {run.error_message}'))

        self.stdout.write(
            (
                'Captura finalizada: '
                f'processadas={summary["total_valid"]}; '
                f'novas={summary["total_created"]}; '
                f'atualizadas={summary["total_updated"]}; '
                f'coletadas={summary["total_collected"]}'
            ),
        )
        log.info('Captura manual finalizada. resumo=%s', summary)
        self._publish_after_capture(summary)

        if has_failure:
            raise CommandError('Uma ou mais coletas terminaram com falha. Consulte ScrapingRun.')

    def _publish_after_capture(self, summary: dict[str, int]) -> None:
        skip_reason = get_auto_publish_skip_reason(total_valid=summary['total_valid'])
        if skip_reason:
            self.stdout.write(self.style.WARNING(skip_reason))
            log.info(skip_reason)
            return

        self.stdout.write('Início da publicação automática do offers.json.')
        result = publish_offers_after_capture()
        if result['error']:
            self.stdout.write(self.style.WARNING(f'Erro na publicação automática: {result["error"]}'))
            log.error('Erro na publicação automática: %s', result)
            return

        self.stdout.write(
            (
                'Publicação automática finalizada: '
                f'ofertas={result["offers_count"]}; '
                f'diff={result["changed"]}; '
                f'commit={result["committed"]}; '
                f'push={result["pushed"]}'
            ),
        )
        log.info('Publicação automática finalizada. resultado=%s', result)

    def _get_marketplaces(self, marketplace_code: str):
        queryset = Marketplace.objects.filter(is_active=True)
        if marketplace_code != 'all':
            queryset = queryset.filter(code=marketplace_code)

        marketplaces = list(queryset.order_by('name'))
        if not marketplaces:
            raise CommandError('Nenhum marketplace ativo encontrado para coleta.')
        return marketplaces
