import json

from django.core.management.base import BaseCommand

from apps.market_intel.services.competitor_radar import (
    build_coverage_report,
    resolve_candidates,
    select_candidate_messages,
)


class Command(BaseCommand):
    help = (
        'Resolve os links de oferta divulgados pelos grupos concorrentes observados '
        '(radar de concorrente) e grava o anúncio correspondente.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--marketplace', default='mercadolivre')
        parser.add_argument('--limit', type=int, default=None, help='Teto de resoluções nesta execução.')
        parser.add_argument('--lookback-hours', type=int, default=None, help='Janela de mensagens observadas.')
        parser.add_argument('--dry-run', action='store_true', help='Resolve sem gravar ObservedOfferLink.')
        parser.add_argument('--no-sleep', action='store_true', help='Sem pausa entre requisições (uso em teste).')
        parser.add_argument(
            '--report',
            action='store_true',
            help='Só imprime a cobertura da janela, sem abrir nenhum link.',
        )
        parser.add_argument('--json', action='store_true', help='Saída em JSON.')

    def handle(self, *args, **options):
        marketplace = options['marketplace']

        if options['report']:
            report = build_coverage_report(
                lookback_hours=options['lookback_hours'] or 24,
                marketplace_code=marketplace,
            )
            self._print(report, options['json'], titulo='Cobertura do radar de concorrente')
            return

        candidatos = select_candidate_messages(
            marketplace,
            lookback_hours=options['lookback_hours'],
            limit=options['limit'],
        )
        if not candidatos:
            self.stdout.write('Nenhum link novo para resolver na janela.')
            return

        stats = resolve_candidates(
            marketplace_code=marketplace,
            lookback_hours=options['lookback_hours'],
            limit=options['limit'],
            dry_run=options['dry_run'],
            sleep=not options['no_sleep'],
        )
        self._print(stats, options['json'], titulo=f'Radar de concorrente ({marketplace})')

    def _print(self, data: dict, as_json: bool, titulo: str) -> None:
        if as_json:
            self.stdout.write(json.dumps(data, ensure_ascii=False))
            return
        self.stdout.write(self.style.SUCCESS(titulo))
        largura = max(len(chave) for chave in data)
        for chave, valor in data.items():
            self.stdout.write(f'  {chave.ljust(largura)}  {valor}')
