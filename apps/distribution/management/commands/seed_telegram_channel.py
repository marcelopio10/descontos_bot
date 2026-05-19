from django.conf import settings
from django.core.management.base import BaseCommand

from apps.distribution.models import SocialChannel


HOMOLOG_CODE = 'telegram_homolog'
HOMOLOG_NAME = 'Telegram homologação'
MAIN_CODE = 'telegram_main'
MAIN_NAME = 'Telegram principal'


class Command(BaseCommand):
    help = 'Cria ou atualiza os canais Telegram de homologação e produção.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--homolog-target',
            default=None,
            help='Chat ID do canal de homologação (@username ou -100...). '
                 'Default: settings.TELEGRAM_CHANNEL_ID_HOMOLOG.',
        )
        parser.add_argument(
            '--main-target',
            default=None,
            help='Chat ID do canal de produção. '
                 'Default: settings.TELEGRAM_CHANNEL_ID_MAIN.',
        )

    def handle(self, *args, **options):
        homolog_target = options['homolog_target'] or settings.TELEGRAM_CHANNEL_ID_HOMOLOG
        main_target = options['main_target'] or settings.TELEGRAM_CHANNEL_ID_MAIN

        self._upsert(code=HOMOLOG_CODE, name=HOMOLOG_NAME, target=homolog_target)
        self._upsert(code=MAIN_CODE, name=MAIN_NAME, target=main_target)

    def _upsert(self, code: str, name: str, target: str) -> None:
        channel, created = SocialChannel.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'channel_type': SocialChannel.ChannelType.TELEGRAM_CHANNEL,
                'target': target,
                'is_enabled': True,
                'link_strategy': SocialChannel.LinkStrategy.AFFILIATE_DIRECT,
            },
        )
        action = 'criado' if created else 'atualizado'
        self.stdout.write(
            self.style.SUCCESS(
                f'Canal Telegram {channel.name} {action} com destino "{channel.target}".',
            ),
        )
