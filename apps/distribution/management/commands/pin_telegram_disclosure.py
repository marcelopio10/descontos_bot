from html import escape

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.distribution.models import SocialChannel
from apps.distribution.services.telegram_client import (
    TelegramClient,
    TelegramClientError,
)


HOMOLOG_CODE = 'telegram_homolog'
MAIN_CODE = 'telegram_main'
DISCLOSURE_URL = 'https://descontos-bot.vercel.app/disclosure'


def build_disclosure_html() -> str:
    base = getattr(
        settings,
        'TELEGRAM_DISCLOSURE_MESSAGE',
        'Como Associado da Amazon, ganho por compras qualificadas.',
    )
    return (
        f'<b>📌 Aviso do canal</b>\n\n'
        f'{escape(base)}\n\n'
        f'Política de cookies e termos: '
        f'<a href="{DISCLOSURE_URL}">{DISCLOSURE_URL}</a>'
    )


class Command(BaseCommand):
    help = 'Envia e fixa a mensagem de disclosure permanente no canal Telegram.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            default=HOMOLOG_CODE,
            choices=[HOMOLOG_CODE, MAIN_CODE],
            help='Código do SocialChannel Telegram alvo.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-envia e re-fixa mesmo se já houver pinned message com este texto.',
        )

    def handle(self, *args, **options):
        channel_code = options['channel']

        if (
            channel_code == MAIN_CODE
            and not settings.ALLOW_PRODUCTION_TELEGRAM_SEND
            and not options['force']
        ):
            raise CommandError(
                'telegram_main bloqueado: defina ALLOW_PRODUCTION_TELEGRAM_SEND=true '
                'ou passe --force.',
            )

        try:
            channel = SocialChannel.objects.get(code=channel_code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(
                f'SocialChannel "{channel_code}" não encontrado. '
                f'Rode `python3 manage.py seed_telegram_channel`.',
            ) from exc

        try:
            client = TelegramClient()
        except TelegramClientError as exc:
            raise CommandError(str(exc)) from exc

        disclosure_html = build_disclosure_html()

        if not options['force']:
            try:
                chat = client.get_chat(channel.target)
            except TelegramClientError as exc:
                raise CommandError(f'Falha ao consultar getChat: {exc}') from exc
            pinned = (chat.get('pinned_message') or {}).get('text', '')
            normalized_existing = _strip_tags(pinned)
            normalized_target = _strip_tags(disclosure_html)
            if normalized_existing and normalized_existing == normalized_target:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Disclosure já fixado em {channel_code} (no-op). Use --force para refazer.',
                    ),
                )
                return

        try:
            send_result = client.send_message(
                chat_id=channel.target,
                text_html=disclosure_html,
                disable_web_page_preview=True,
            )
        except TelegramClientError as exc:
            raise CommandError(f'Falha ao enviar disclosure: {exc}') from exc

        if not send_result.success or not send_result.message_id:
            raise CommandError(
                f'Envio de disclosure não retornou message_id: {send_result.error_message}',
            )

        try:
            client.pin_chat_message(
                chat_id=channel.target,
                message_id=send_result.message_id,
                disable_notification=True,
            )
        except TelegramClientError as exc:
            raise CommandError(f'Falha ao fixar disclosure: {exc}') from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Disclosure publicado e fixado em {channel_code} '
                f'(message_id={send_result.message_id}).',
            ),
        )


def _strip_tags(html: str) -> str:
    import re
    return re.sub(r'<[^>]+>', '', html or '').strip()
