import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.analytics.services.operational_metrics import (
    DEFAULT_DAYS,
    OperationalPanel,
    build_operational_panel,
)


PANEL_FILENAME = 'painel-operacional.json'


class Command(BaseCommand):
    help = (
        'Imprime o painel operacional mínimo (envios/dia por canal, '
        'ofertas coletadas/válidas por marketplace, runs FAILED de scraping '
        'e curadoria, última coleta do observer) e grava '
        f'site/{PANEL_FILENAME}.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=DEFAULT_DAYS,
            help=f'Janela de análise em dias (default {DEFAULT_DAYS}).',
        )

    def handle(self, *args, **options):
        days = options['days']
        panel = build_operational_panel(days=days)

        self._print_panel(panel)

        output_path = self._write_json(panel)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'JSON gravado em {output_path}'))

    # -- impressão no terminal -------------------------------------------------

    def _print_panel(self, panel: OperationalPanel) -> None:
        self.stdout.write(
            f'Painel operacional — janela de {panel.days} dia(s) '
            f'(gerado em {panel.generated_at:%d/%m/%Y %H:%M})'
        )
        self.stdout.write('=' * 78)

        self._print_deliveries(panel)
        self._print_scraping(panel)
        self._print_curation(panel)
        self._print_observer(panel)

    def _print_deliveries(self, panel: OperationalPanel) -> None:
        deliveries = panel.deliveries
        self.stdout.write('')
        self.stdout.write('Envios por dia/canal (delivery_status=sent)')
        self.stdout.write('-' * 78)
        if not deliveries.rows:
            self.stdout.write('  (nenhum envio no período)')
        else:
            self.stdout.write(f'  {"dia":12} {"canal":30} {"enviados":>10}')
            for row in deliveries.rows:
                self.stdout.write(
                    f'  {row.day.isoformat():12} {row.channel_name[:30]:30} '
                    f'{row.sent_count:>10}'
                )
            self.stdout.write('')
            self.stdout.write('  Totais por canal:')
            for channel_code, total in sorted(
                deliveries.totals_by_channel.items(), key=lambda kv: -kv[1]
            ):
                self.stdout.write(f'    {channel_code:30} {total:>10}')
        self.stdout.write(f'  Total geral enviado no período: {deliveries.total_sent}')

    def _print_scraping(self, panel: OperationalPanel) -> None:
        scraping = panel.scraping
        self.stdout.write('')
        self.stdout.write('Scraping — coletado/válido por marketplace')
        self.stdout.write('-' * 78)
        if not scraping.by_marketplace:
            self.stdout.write('  (nenhum run de scraping no período)')
        else:
            self.stdout.write(
                f'  {"marketplace":22} {"runs":>6} {"coletado":>10} {"válido":>10}'
            )
            for row in scraping.by_marketplace:
                self.stdout.write(
                    f'  {row.marketplace_name[:22]:22} {row.run_count:>6} '
                    f'{row.total_collected:>10} {row.total_valid:>10}'
                )
        self.stdout.write('')
        self.stdout.write(
            f'  Runs por status: '
            + (', '.join(f'{k}={v}' for k, v in sorted(scraping.runs_by_status.items())) or '-')
        )
        self.stdout.write(
            f'  Total de runs: {scraping.total_runs} | FAILED: {scraping.failed_runs} '
            f'({scraping.failed_rate_pct}%)'
        )

    def _print_curation(self, panel: OperationalPanel) -> None:
        curation = panel.curation
        self.stdout.write('')
        self.stdout.write('Curadoria — runs por status')
        self.stdout.write('-' * 78)
        self.stdout.write(
            '  '
            + (', '.join(f'{k}={v}' for k, v in sorted(curation.runs_by_status.items())) or '(nenhum run no período)')
        )
        self.stdout.write(
            f'  Total de runs: {curation.total_runs} | FAILED: {curation.failed_runs} '
            f'({curation.failed_rate_pct}%)'
        )

    def _print_observer(self, panel: OperationalPanel) -> None:
        observer = panel.observer
        self.stdout.write('')
        self.stdout.write('Observer (market intel) — última coleta')
        self.stdout.write('-' * 78)
        if observer.last_message_collected_at:
            self.stdout.write(
                f'  Última mensagem coletada: '
                f'{observer.last_message_collected_at:%d/%m/%Y %H:%M} '
                f'(grupo: {observer.last_message_group_name}) '
                f'— há {observer.hours_since_last_collection}h'
            )
        else:
            self.stdout.write('  Nenhuma mensagem observada registrada.')
        if observer.last_daily_report_date:
            self.stdout.write(
                f'  Último relatório diário: {observer.last_daily_report_date.isoformat()}'
            )
        else:
            self.stdout.write('  Nenhum relatório diário (MarketIntelDailyReport) registrado.')

        status_label = 'ATRASADO (>24h sem coleta)' if observer.is_stale else 'OK'
        style = self.style.WARNING if observer.is_stale else self.style.SUCCESS
        self.stdout.write(f'  Status: {style(status_label)}')

    # -- gravação do JSON -------------------------------------------------------

    def _write_json(self, panel: OperationalPanel) -> Path:
        payload = _panel_to_dict(panel)
        output_path = Path(settings.SITE_PUBLIC_DIR) / PANEL_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding='utf-8',
        )
        return output_path


def _panel_to_dict(panel: OperationalPanel) -> dict:
    """Converte o dataclass aninhado em dict serializável.

    Só contagens/agregados operacionais (envios, runs, timestamps) — sem
    tokens, credenciais ou preço histórico individual.
    """
    return asdict(panel)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f'Tipo não serializável: {type(value)}')
