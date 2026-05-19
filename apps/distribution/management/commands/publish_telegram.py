import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.services.selector import (
    get_selection_config,
    select_offers_for_channel,
)
from apps.curation.services.telegram_message_builder import build_telegram_payload
from apps.distribution.models import SocialChannel
from apps.distribution.services.telegram_delivery import deliver_offer_to_telegram


HOMOLOG_CODE = 'telegram_homolog'
MAIN_CODE = 'telegram_main'

logger = logging.getLogger('apps.distribution.telegram')


class Command(BaseCommand):
    help = 'Publica ofertas elegíveis no canal Telegram (homologação por padrão).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            default=HOMOLOG_CODE,
            choices=[HOMOLOG_CODE, MAIN_CODE],
            help='Código do SocialChannel Telegram alvo.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de ofertas a publicar nesta execução (após o selector).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista as ofertas selecionadas e imprime a caption sem enviar nada.',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Executa 1 ciclo e sai (loop infinito é responsabilidade do operador).',
        )

    def handle(self, *args, **options):
        channel_code = options['channel']
        dry_run = options['dry_run']

        if channel_code == MAIN_CODE and not settings.ALLOW_PRODUCTION_TELEGRAM_SEND:
            raise CommandError(
                'telegram_main bloqueado: defina ALLOW_PRODUCTION_TELEGRAM_SEND=true.',
            )

        try:
            channel = SocialChannel.objects.get(code=channel_code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(
                f'SocialChannel "{channel_code}" não encontrado. '
                f'Rode `python3 manage.py seed_telegram_channel`.',
            ) from exc

        if not channel.is_enabled:
            raise CommandError(f'Canal {channel_code} desabilitado.')

        offers = select_offers_for_channel(channel, get_selection_config())
        if options['limit'] is not None:
            offers = offers[: max(0, options['limit'])]

        self.stdout.write(f'Selecionadas {len(offers)} oferta(s) para {channel_code}.')

        if not offers:
            return

        if dry_run:
            for offer in offers:
                payload = build_telegram_payload(offer, channel)
                self.stdout.write('-' * 60)
                self.stdout.write(f'offer_id={offer.id} title={offer.title!r}')
                self.stdout.write(f'use_photo={payload.use_photo} photo_url={payload.photo_url}')
                self.stdout.write(f'button_url={payload.final_url}')
                self.stdout.write('caption:')
                self.stdout.write(payload.caption)
            self.stdout.write(self.style.WARNING('dry_run ativo: nenhuma mensagem real enviada.'))
            return

        sent_count = 0
        for offer in offers:
            result = deliver_offer_to_telegram(offer, channel)
            if result.sent:
                sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Ciclo concluído. Enviadas {sent_count}/{len(offers)} '
                f'no canal {channel_code}.',
            ),
        )
