from django.core.management.base import BaseCommand, CommandError

from apps.market_intel.services.ingestion import import_observed_messages
from apps.market_intel.services.whatsapp_observer_client import (
    WhatsAppObserverClient,
    WhatsAppObserverClientError,
)


class Command(BaseCommand):
    help = 'Coleta mensagens observadas dos grupos WhatsApp allowlisted via wa_service.'

    def add_arguments(self, parser):
        parser.add_argument('--base-url', default=None)
        parser.add_argument('--timeout', type=int, default=30)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        client = WhatsAppObserverClient(base_url=options['base_url'], timeout=options['timeout'])
        try:
            payload = client.collect()
        except WhatsAppObserverClientError as exc:
            raise CommandError(str(exc)) from exc

        messages_count = len(payload.get('messages') or [])
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'dry-run: {messages_count} mensagens recebidas do observer.'))
            return

        result = import_observed_messages(payload)
        self.stdout.write(
            self.style.SUCCESS(
                'observer importado: '
                f"created={result['created']} updated={result['updated']} skipped={result['skipped']}"
            )
        )
