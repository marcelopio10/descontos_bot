from django.core.management.base import BaseCommand

from apps.market_intel.services.incremental import build_learning_snapshot


class Command(BaseCommand):
    help = 'Gera snapshot shadow de inteligência de mercado a partir do SQLite.'

    def add_arguments(self, parser):
        parser.add_argument('--lookback-hours', type=int, default=24)

    def handle(self, *args, **options):
        snapshot = build_learning_snapshot(lookback_hours=options['lookback_hours'])
        self.stdout.write(self.style.SUCCESS(
            f'snapshot shadow criado: id={snapshot.id} sample_size={snapshot.sample_size}',
        ))
