"""Ingestão automática das vendas do painel de afiliados do Mercado Livre.

Diferente dos `ingest_affiliate_*` existentes, que dependem de o dono colar um
JSON copiado do DevTools, esta rotina fala direto com o endpoint do painel
usando o `ML_COOKIE` que o projeto já mantém — por isso pode rodar em timer.

Uso típico:

    manage.py ingest_ml_affiliate_sales --days 45          # janela padrão do timer
    manage.py ingest_ml_affiliate_sales --since 2026-02-25 --until 2026-08-24
    manage.py ingest_ml_affiliate_sales --days 7 --dry-run
    manage.py ingest_ml_affiliate_sales --from-file data/exports/affiliate_ml/ml_sales.json

A janela do timer é propositalmente larga e sobreposta: venda entra como
`IN_REVIEW` e só vira `APPROVED`/`REJECTED` semanas depois, então reler o
passado recente é o que mantém o status correto. A idempotência é por `sale_id`.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.affiliate_parsers.mercadolivre_sales import (
    ingest_ml_sales,
)
from apps.analytics.services.ml_affiliate_sales_client import (
    MLAffiliateAuthError,
    MLAffiliateFetchError,
    fetch_sales,
    parse_sales_payload,
)

DEFAULT_DAYS = 45


class Command(BaseCommand):
    help = (
        'Coleta as vendas do painel de afiliados do Mercado Livre (venda a venda, '
        'com status) e persiste em MLAffiliateSale, de forma idempotente.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=DEFAULT_DAYS,
            help=f'Janela em dias contada de hoje para trás (default: {DEFAULT_DAYS}).',
        )
        parser.add_argument('--since', help='Início da janela (AAAA-MM-DD).')
        parser.add_argument('--until', help='Fim da janela (AAAA-MM-DD).')
        parser.add_argument(
            '--from-file',
            help='Lê um JSON já salvo do painel em vez de chamar o ML (backfill/teste).',
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=40,
            help='Teto de páginas por execução (default: 40, 50 vendas por página).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Roda tudo sem persistir (a transação sofre rollback no fim).',
        )

    def handle(self, *args, **options):
        start, end = self._window(options)

        if options['from_file']:
            records = self._records_from_file(options['from_file'])
            origem = Path(options['from_file']).name
        else:
            try:
                records = fetch_sales(
                    start=start,
                    end=end,
                    max_pages=options['max_pages'],
                )
            except MLAffiliateAuthError as exc:
                raise CommandError(f'Autenticação no ML falhou: {exc}') from exc
            except MLAffiliateFetchError as exc:
                raise CommandError(f'Falha ao buscar vendas: {exc}') from exc
            origem = f'dashboard/sales/general {start:%Y-%m-%d}..{end:%Y-%m-%d}'

        if not records:
            self.stdout.write(self.style.WARNING(
                f'Nenhuma venda no período {start:%d/%m/%Y}..{end:%d/%m/%Y}. '
                'Nada a importar.'
            ))
            return

        result = ingest_ml_sales(
            records,
            filename=origem,
            commit=not options['dry_run'],
        )

        modo = 'DRY-RUN' if options['dry_run'] else 'commit'
        self.stdout.write(self.style.SUCCESS(
            f'Lote #{result.batch.id} ({modo}) — '
            f'{len(records)} venda(s) no painel · '
            f'novas={result.created} atualizadas={result.updated} '
            f'status_mudou={result.status_changed} '
            f'compra_própria_auto={result.auto_marked_own} '
            f'ofertas_resolvidas={result.resolved_offers} · '
            f'período={result.period_start}..{result.period_end}'
        ))
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f'  ! {warning}'))

        if result.auto_marked_own:
            self.stdout.write(self.style.WARNING(
                f'  → {result.auto_marked_own} venda(s) marcada(s) como compra própria '
                'por status REJECTED. Marcação manual (Admin) tem prioridade e nunca '
                'é sobrescrita por esta rotina.'
            ))

    def _window(self, options) -> tuple[date, date]:
        since = _parse_day(options.get('since'), '--since')
        until = _parse_day(options.get('until'), '--until')
        today = date.today()

        if since and until:
            if since > until:
                raise CommandError('--since não pode ser depois de --until.')
            return since, until
        if since:
            return since, today
        if until:
            return until - timedelta(days=options['days']), until

        days = options['days']
        if days <= 0:
            raise CommandError('--days precisa ser positivo.')
        return today - timedelta(days=days), today

    def _records_from_file(self, raw_path: str):
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise CommandError(f'Arquivo não encontrado: {path}')
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except json.JSONDecodeError as exc:
            raise CommandError(f'JSON inválido em {path}: {exc}') from exc

        records = parse_sales_payload(payload)
        if not records:
            raise CommandError(
                f'Nenhuma venda reconhecida em {path} — o arquivo tem o formato do painel?'
            )
        return records


def _parse_day(value, flag: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise CommandError(f'{flag} inválido: "{value}". Use AAAA-MM-DD.') from exc
