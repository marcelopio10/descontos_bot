import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.distribution.services.telegram_client import (
    TelegramClient,
    TelegramClientError,
)


class Command(BaseCommand):
    help = (
        'Long-poll do bot de handoff por N segundos e lista chat_ids que '
        'mandaram mensagem. Use pra descobrir seu chat_id pessoal: rode o '
        'comando, mande /start (ou qualquer mensagem) pro bot, e copie o '
        'valor exibido pro INSTAGRAM_HANDOFF_CHAT_ID no .env.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--seconds',
            type=int,
            default=60,
            help='Tempo total de escuta em segundos (default: 60).',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'INSTAGRAM_HANDOFF_BOT_TOKEN', '')
        if not token:
            raise CommandError(
                'INSTAGRAM_HANDOFF_BOT_TOKEN não está configurado no .env.',
            )

        client = TelegramClient(token=token)
        deadline = time.monotonic() + options['seconds']
        offset: int | None = None
        seen: dict[int, dict] = {}

        self.stdout.write(
            self.style.WARNING(
                f'Escutando updates por {options["seconds"]}s — '
                'mande qualquer mensagem pro bot agora.',
            ),
        )

        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            poll_timeout = min(25, remaining)
            try:
                updates = client.get_updates(
                    offset=offset,
                    timeout=poll_timeout,
                    allowed_updates=['message', 'callback_query'],
                )
            except TelegramClientError as exc:
                self.stderr.write(self.style.ERROR(f'Erro getUpdates: {exc}'))
                time.sleep(2)
                continue

            for update in updates:
                update_id = update.get('update_id')
                if isinstance(update_id, int):
                    offset = update_id + 1

                source = update.get('message') or update.get('callback_query') or {}
                origin = source.get('from') or {}
                chat = source.get('chat') or {}
                chat_id = chat.get('id') or origin.get('id')
                if chat_id is None:
                    continue
                if chat_id in seen:
                    continue
                seen[chat_id] = {
                    'chat_id': chat_id,
                    'username': origin.get('username') or '',
                    'first_name': origin.get('first_name') or '',
                    'type': chat.get('type') or 'private',
                }
                self.stdout.write(
                    self.style.SUCCESS(
                        f'chat_id={chat_id} '
                        f'username=@{origin.get("username") or "-"} '
                        f'first_name={origin.get("first_name") or "-"} '
                        f'type={chat.get("type") or "-"}',
                    ),
                )

        if not seen:
            self.stdout.write(
                self.style.WARNING(
                    'Nenhum chat_id capturado. Garanta que mandou mensagem pro '
                    'bot certo e tente de novo com --seconds maior.',
                ),
            )
            return

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Resumo:'))
        for entry in seen.values():
            self.stdout.write(f'  {entry}')
