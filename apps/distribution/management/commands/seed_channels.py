from django.core.management.base import BaseCommand

from apps.distribution.models import SocialChannel


HOMOLOGATION_CODE = 'whatsapp_main'
HOMOLOGATION_NAME = 'WhatsApp homologação'
HOMOLOGATION_TARGET = 'descontos.bot - Homologação'
PRODUCTION_CODE = 'whatsapp_principal'
PRODUCTION_NAME = 'WhatsApp principal'
PRODUCTION_TARGET = 'descontos.bot'


class Command(BaseCommand):
    help = 'Cria ou atualiza os canais WhatsApp de homologação e produção.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target',
            default=HOMOLOGATION_TARGET,
            help='Nome exato do grupo WhatsApp de homologação.',
        )
        parser.add_argument(
            '--production-target',
            default=PRODUCTION_TARGET,
            help='Nome exato do grupo WhatsApp de produção.',
        )

    def handle(self, *args, **options):
        self._upsert(
            code=HOMOLOGATION_CODE,
            name=HOMOLOGATION_NAME,
            target=options['target'],
        )
        self._upsert(
            code=PRODUCTION_CODE,
            name=PRODUCTION_NAME,
            target=options['production_target'],
        )

    def _upsert(self, code: str, name: str, target: str) -> None:
        channel, created = SocialChannel.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'channel_type': SocialChannel.ChannelType.WHATSAPP_GROUP,
                'target': target,
                'is_enabled': True,
                'link_strategy': SocialChannel.LinkStrategy.BRIDGE_ONLY,
            },
        )
        action = 'criado' if created else 'atualizado'
        self.stdout.write(
            self.style.SUCCESS(
                f'Canal {channel.name} {action} com destino "{channel.target}".',
            ),
        )
