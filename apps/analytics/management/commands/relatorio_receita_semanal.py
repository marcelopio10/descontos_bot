"""Relatório semanal que cruza o que publicamos com o que vendeu.

Item 7 da Onda 1. Roda em timer semanal, logo depois da ingestão do painel do
ML, porque é dela que vem o lado da venda.

    manage.py relatorio_receita_semanal                    # 8 semanas, WhatsApp
    manage.py relatorio_receita_semanal --weeks 4
    manage.py relatorio_receita_semanal --end 2026-07-31   # janela histórica
    manage.py relatorio_receita_semanal --alert            # avisa o operador
"""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.alertas import enviar_alerta_operador
from apps.analytics.services.revenue_loop import (
    DEFAULT_CHANNEL_CODE,
    DEFAULT_WEEKS,
    build_revenue_loop_report,
)

# `data/exports/` é ignorado pelo git de propósito: o relatório tem receita e
# não pode ir para `site/`, que é publicado.
EXPORT_DIRNAME = 'data/exports/receita_semanal'


class Command(BaseCommand):
    help = (
        'Cruza envios com vendas do painel do ML por faixa de preço, categoria '
        'e caminho de publicação. Grava JSON em data/exports/receita_semanal/.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--weeks',
            type=int,
            default=DEFAULT_WEEKS,
            help=f'Janela em semanas (default: {DEFAULT_WEEKS}).',
        )
        parser.add_argument(
            '--channel',
            default=DEFAULT_CHANNEL_CODE,
            help=f'Code do SocialChannel (default: {DEFAULT_CHANNEL_CODE}).',
        )
        parser.add_argument(
            '--end',
            help='Fim da janela (AAAA-MM-DD). Default: hoje.',
        )
        parser.add_argument(
            '--no-json',
            action='store_true',
            help='Só imprime, não grava arquivo.',
        )
        parser.add_argument(
            '--alert',
            action='store_true',
            help='Envia o resumo para o Telegram do operador (usado pelo timer).',
        )

    def handle(self, *args, **options):
        end = None
        if options['end']:
            try:
                end = datetime.strptime(options['end'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--end inválida, use o formato AAAA-MM-DD.')

        try:
            report = build_revenue_loop_report(
                weeks=options['weeks'],
                channel_code=options['channel'],
                end=end,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._print(report)

        if not options['no_json']:
            path = self._write_json(report)
            self.stdout.write(f'\nJSON: {path}')

        if options['alert']:
            enviar_alerta_operador(self._alert_text(report), categoria='receita_semanal')

    def _print(self, report):
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(
            f'\nPublicado × vendido — {report.channel_code} · '
            f'{report.start:%d/%m/%Y} a {report.end:%d/%m/%Y}'
        ))
        w(
            f'Envios: {report.deliveries_total} ({report.deliveries_ml} de Mercado '
            f'Livre, os únicos cruzáveis) · Vendas de cliente: {report.sales_total} · '
            f'Comissão: R$ {report.commission_total} '
            f'(aprovada R$ {report.commission_approved}, '
            f'em revisão R$ {report.commission_in_review})'
        )
        w(f'Comissão por mil envios de ML: R$ {report.commission_per_thousand}')

        w(self.style.MIGRATE_HEADING('\nPor faixa de preço'))
        w(f'{"faixa":<20}{"envios":>8}{"%":>7}{"vendas":>8}{"comissão":>12}{"%":>7}{"R$/1k":>10}')
        for row in report.bands:
            w(
                f'{row.label:<20}{row.deliveries:>8}{row.deliveries_pct:>7.1f}'
                f'{row.sales:>8}{"R$ " + str(row.commission):>12}'
                f'{row.commission_pct:>7.1f}{row.commission_per_thousand:>10}'
            )

        w(self.style.MIGRATE_HEADING('\nPor categoria (amostra: só vendas casadas com oferta nossa)'))
        w(f'{"categoria":<28}{"envios":>8}{"%":>7}{"vendas":>8}{"comissão":>12}')
        for row in report.categories[:12]:
            w(
                f'{row.name[:27]:<28}{row.deliveries:>8}{row.deliveries_pct:>7.1f}'
                f'{row.sales:>8}{"R$ " + str(row.commission):>12}'
            )

        w(self.style.MIGRATE_HEADING('\nPor caminho de publicação'))
        w(f'{"caminho":<20}{"envios":>8}{"%":>7}{"vendas":>8}{"comissão":>12}')
        for row in report.paths:
            w(
                f'{row.label:<20}{row.deliveries:>8}{row.deliveries_pct:>7.1f}'
                f'{row.sales_matched:>8}{"R$ " + str(row.commission):>12}'
            )

        if report.gaps:
            w(self.style.MIGRATE_HEADING('\nVendeu e não publicamos nada da mesma família'))
            for row in report.gaps:
                w(
                    f'  {row.family:<24} {row.sales} venda(s) · R$ {row.commission} · '
                    f'ex.: {row.sample_title[:50]}'
                )

        for warning in report.warnings:
            w(self.style.WARNING(f'  ! {warning}'))

    def _write_json(self, report) -> Path:
        directory = Path(settings.BASE_DIR) / EXPORT_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{report.end:%Y-%m-%d}.json'
        path.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        return path

    def _alert_text(self, report) -> str:
        top_band = max(report.bands, key=lambda row: row.commission, default=None)
        linhas = [
            f'Semanal {report.start:%d/%m} a {report.end:%d/%m} — '
            f'{report.deliveries_ml} envios de ML, {report.sales_total} vendas, '
            f'R$ {report.commission_total} de comissão '
            f'(R$ {report.commission_per_thousand} por mil envios).',
        ]
        if top_band and top_band.commission:
            linhas.append(
                f'Faixa que mais rendeu: {top_band.label} '
                f'({top_band.commission_pct:.0f}% da comissão em '
                f'{top_band.deliveries_pct:.0f}% dos envios).'
            )
        if report.gaps:
            gap = report.gaps[0]
            linhas.append(f'Maior lacuna: {gap.family} vendeu e não publicamos.')
        linhas.extend(f'! {w}' for w in report.warnings[:2])
        return '\n'.join(linhas)
