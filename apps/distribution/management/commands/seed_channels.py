from django.core.management.base import BaseCommand

from apps.distribution.models import SocialChannel


class Command(BaseCommand):
    help = 'Cria ou atualiza o canal WhatsApp principal.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target',
            default='grupo-ofertas-homologacao',
            help='Nome exato do grupo WhatsApp usado pelo wa_service.',
        )

    def handle(self, *args, **options):
        channel, created = SocialChannel.objects.update_or_create(
            code='whatsapp_principal',
            defaults={
                'name': 'WhatsApp principal',
                'channel_type': SocialChannel.ChannelType.WHATSAPP,
                'target': options['target'],
                'is_enabled': True,
            },
        )
        action = 'criado' if created else 'atualizado'
        self.stdout.write(
            self.style.SUCCESS(
                f'Canal {channel.name} {action} com destino "{channel.target}".',
            ),
        )
