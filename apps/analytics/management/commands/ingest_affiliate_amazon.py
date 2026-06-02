from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.affiliate_parsers.amazon import parse_amazon_tsv
from apps.analytics.services.affiliate_summary import publish_affiliate_summary


class Command(BaseCommand):
    help = (
        'Importa relatório por ASIN do Amazon Associates (TSV/CSV). '
        'Período deve ser informado manualmente — Amazon não inclui data no arquivo.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            required=True,
            help='Caminho do arquivo TSV exportado do painel Amazon Associates.',
        )
        parser.add_argument(
            '--period-start',
            required=True,
            help='Início do período (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--period-end',
            required=True,
            help='Fim do período (YYYY-MM-DD).',
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

        try:
            period_start = datetime.strptime(options['period_start'], '%Y-%m-%d').date()
            period_end = datetime.strptime(options['period_end'], '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError(f'Data inválida (use YYYY-MM-DD): {exc}')

        payload = file_path.read_bytes()
        result = parse_amazon_tsv(
            payload,
            period_start=period_start,
            period_end=period_end,
            filename=file_path.name,
            commit=not options['dry_run'],
        )

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
