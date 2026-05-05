from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.models import Marketplace
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping


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

        for marketplace in marketplaces:
            self.stdout.write(f'Coletando ofertas de {marketplace.name}...')
            result = run_marketplace_scraping(marketplace=marketplace, max_pages=max_pages)
            run = result.run

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

        if has_failure:
            raise CommandError('Uma ou mais coletas terminaram com falha. Consulte ScrapingRun.')

    def _get_marketplaces(self, marketplace_code: str):
        queryset = Marketplace.objects.filter(is_active=True)
        if marketplace_code != 'all':
            queryset = queryset.filter(code=marketplace_code)

        marketplaces = list(queryset.order_by('name'))
        if not marketplaces:
            raise CommandError('Nenhum marketplace ativo encontrado para coleta.')
        return marketplaces
