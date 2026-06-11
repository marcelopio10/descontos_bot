import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.market_intel.models import MarketIntelDailyReport
from apps.market_intel.services.reports import build_daily_report_payload, generate_daily_report


class Command(BaseCommand):
    help = 'Publica JSON de inteligência de grupos WhatsApp para o site estático.'

    def add_arguments(self, parser):
        parser.add_argument('--date', default='')
        parser.add_argument('--output', default='site/market-intel.json')

    def handle(self, *args, **options):
        report_date = date.fromisoformat(options['date']) if options['date'] else None
        if report_date:
            report = generate_daily_report(report_date)
        else:
            report = MarketIntelDailyReport.objects.order_by('-date').first()
            if report is None:
                raise CommandError('Nenhum relatório disponível. Rode analyze_whatsapp_offer_groups antes.')

        payload = build_daily_report_payload(report)
        output_path = Path(options['output'])
        if not output_path.is_absolute():
            output_path = Path(settings.BASE_DIR) / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report.site_payload_path = str(output_path)
        report.save(update_fields=['site_payload_path', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(f'market-intel publicado: {output_path}'))
