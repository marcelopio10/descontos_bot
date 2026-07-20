from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.affiliate_parsers.shopee import parse_shopee_report
from apps.analytics.services.affiliate_summary import publish_affiliate_summary


class Command(BaseCommand):
    help = (
        'Importa o relatório de conversão do Shopee Affiliate Program (CSV/TSV). '
        'RESTR-04: Shopee é a única fonte com relatório exportável oficialmente '
        '(ML e Amazon são manuais — ver ingest_affiliate_mercadolivre/ingest_affiliate_amazon). '
        'ATENÇÃO: os nomes de coluna aceitos são uma melhor estimativa — este parser NÃO '
        'foi validado contra um export real do painel Shopee. Confira o cabeçalho do '
        'primeiro arquivo real contra COLUMN_ALIASES em '
        'apps/analytics/services/affiliate_parsers/shopee.py e ajuste se divergir.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            required=True,
            help='Caminho do arquivo CSV/TSV exportado do painel Shopee Affiliate.',
        )
        parser.add_argument(
            '--period-start',
            default=None,
            help=(
                'Início do período (YYYY-MM-DD). Opcional — se omitido, o parser tenta '
                'derivar do min/max das colunas de data do arquivo (conversion_time/click_time).'
            ),
        )
        parser.add_argument(
            '--period-end',
            default=None,
            help='Fim do período (YYYY-MM-DD). Ver --period-start.',
        )
        parser.add_argument(
            '--include-pending',
            action='store_true',
            help=(
                'Inclui linhas com status "pendente"/"pending" na agregação. '
                'Por padrão só conversões confirmadas são contabilizadas '
                '(canceladas/inválidas são sempre ignoradas).'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Roda o parser sem persistir nada.',
        )
        parser.add_argument(
            '--no-publish',
            action='store_true',
            help='Não atualiza affiliate-summary.json após importação.',
        )

    def handle(self, *args, **options):
        file_path = Path(options['file']).expanduser()
        if not file_path.exists():
            raise CommandError(f'Arquivo não encontrado: {file_path}')

        period_start = self._parse_date(options['period_start'], '--period-start')
        period_end = self._parse_date(options['period_end'], '--period-end')
        if (period_start is None) != (period_end is None):
            raise CommandError(
                '--period-start e --period-end precisam ser informados juntos '
                '(ou nenhum dos dois, para derivar do arquivo).'
            )

        payload = file_path.read_bytes()

        try:
            result = parse_shopee_report(
                payload,
                period_start=period_start,
                period_end=period_end,
                filename=file_path.name,
                commit=not options['dry_run'],
                include_pending=options['include_pending'],
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f'Lote #{result.batch.id} ({"DRY-RUN" if options["dry_run"] else "commit"}) — '
            f'importado={result.imported} ignorado={result.skipped} '
            f'período={result.period_start}..{result.period_end}'
        ))
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f'  ! {warning}'))

        if not options['dry_run'] and not options['no_publish']:
            summary = publish_affiliate_summary()
            self.stdout.write(self.style.SUCCESS(
                f'affiliate-summary.json atualizado em {summary.output_path}'
            ))

    @staticmethod
    def _parse_date(raw, flag_name):
        if not raw:
            return None
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError(f'Data inválida em {flag_name} (use YYYY-MM-DD): {exc}')
