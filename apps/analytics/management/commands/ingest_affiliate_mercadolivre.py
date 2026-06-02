import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.affiliate_parsers.mercadolivre import (
    parse_mercadolivre_payload,
)
from apps.analytics.services.affiliate_summary import publish_affiliate_summary


class Command(BaseCommand):
    help = (
        'Importa relatório do painel Mercado Livre Afiliados (JSON copiado '
        'do DevTools, pois não há export oficial).'
    )

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            '--file',
            help='Caminho de um arquivo .json salvo do DevTools.',
        )
        source.add_argument(
            '--stdin',
            action='store_true',
            help='Lê o JSON do stdin (cole e Ctrl-D).',
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
        if options['file']:
            path = Path(options['file']).expanduser()
            if not path.exists():
                raise CommandError(f'Arquivo não encontrado: {path}')
            payload = path.read_bytes()
            filename = path.name
        else:
            payload = sys.stdin.read().encode('utf-8')
            filename = 'stdin'

        result = parse_mercadolivre_payload(
            payload,
            filename=filename,
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
