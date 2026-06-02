from django.core.management.base import BaseCommand

from apps.analytics.services.affiliate_summary import (
    DEFAULT_WINDOW_DAYS,
    publish_affiliate_summary,
)


class Command(BaseCommand):
    help = (
        'Regera site/affiliate-summary.json a partir das conversões já '
        'importadas, sem reprocessar arquivos.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-days',
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=f'Janela de agregação em dias (default {DEFAULT_WINDOW_DAYS}).',
        )

    def handle(self, *args, **options):
        result = publish_affiliate_summary(window_days=options['window_days'])
        totals = result.totals
        self.stdout.write(self.style.SUCCESS(
            f'{result.output_path} — janela {result.window_days}d, '
            f'cliques={totals["clicks"]} conv={totals["conversions"]} '
            f'comissão=R$ {totals["commission_brl"]}'
        ))
