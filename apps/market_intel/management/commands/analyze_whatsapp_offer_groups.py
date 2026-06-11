from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.market_intel.services.reports import generate_daily_report


class Command(BaseCommand):
    help = 'Gera relatório agregado de inteligência dos grupos WhatsApp observados.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=1)
        parser.add_argument('--date', default='')

    def handle(self, *args, **options):
        if options['date']:
            report_date = date.fromisoformat(options['date'])
        else:
            report_date = timezone.localdate() - timedelta(days=max(options['days'] - 1, 0))

        report = generate_daily_report(report_date)
        self.stdout.write(
            self.style.SUCCESS(
                f'relatório gerado: date={report.date} messages={report.messages_analyzed} groups={report.groups_analyzed}'
            )
        )
