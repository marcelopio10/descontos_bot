from django.core.management.base import BaseCommand, CommandError

from apps.market_intel.services.incremental import (
    build_learning_snapshot,
    ingest_incremental_messages,
)
from apps.market_intel.services.ingestion import import_observed_messages
from apps.market_intel.services.whatsapp_observer_client import (
    WhatsAppObserverClient,
    WhatsAppObserverClientError,
)


class Command(BaseCommand):
    help = 'Processa inteligência de mercado incremental em micro-lote, sem publicar ofertas.'

    def add_arguments(self, parser):
        parser.add_argument('--base-url', default=None)
        parser.add_argument('--timeout', type=int, default=30)
        parser.add_argument('--lookback-hours', type=int, default=24)
        parser.add_argument('--snapshot', action='store_true')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        client = WhatsAppObserverClient(base_url=options['base_url'], timeout=options['timeout'])
        try:
            payload = client.collect()
        except WhatsAppObserverClientError as exc:
            raise CommandError(str(exc)) from exc

        received = len(payload.get('messages') or [])
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'dry-run: {received} mensagens recebidas; nenhuma escrita realizada.'))
            return

        imported = import_observed_messages(payload)
        incremental = ingest_incremental_messages(lookback_hours=options['lookback_hours'])
        snapshot = build_learning_snapshot(lookback_hours=options['lookback_hours']) if options['snapshot'] else None
        message = (
            f'incremental: received={received} created={imported["created"]} '
            f'updated={imported["updated"]} skipped={imported["skipped"]} '
            f'processed={incremental["processed"]} opportunities={incremental["opportunities"]}'
        )
        if snapshot:
            message += f' snapshot={snapshot.id}'
        self.stdout.write(self.style.SUCCESS(message))
