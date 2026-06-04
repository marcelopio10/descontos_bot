import logging
import os
import signal
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.distribution.services.telegram_client import (
    TelegramClient,
    TelegramClientError,
)
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.instagram_handoff_telegram import (
    MARK_POSTED_CALLBACK_PREFIX,
    mark_post_as_posted,
)


log = logging.getLogger(__name__)

OFFSET_PATH = Path(settings.BASE_DIR) / 'logs' / 'handoff_offset.txt'
LOCK_PATH = Path('/tmp/instagram_handoff_listener.lock')
POLL_TIMEOUT = 25
DEFAULT_LOOP_SLEEP = 1.0


class Command(BaseCommand):
    help = (
        'Daemon long-poll que escuta cliques no botão "Marcar como postado" '
        'do handoff Telegram e atualiza o status do InstagramPost.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Roda um único ciclo de getUpdates e sai (para debug).',
        )

    def handle(self, *args, **options):
        token = getattr(settings, 'INSTAGRAM_HANDOFF_BOT_TOKEN', '')
        allowed_chat_id = getattr(settings, 'INSTAGRAM_HANDOFF_CHAT_ID', '')
        if not token:
            raise CommandError(
                'INSTAGRAM_HANDOFF_BOT_TOKEN não está configurado no .env.',
            )
        if not allowed_chat_id:
            raise CommandError(
                'INSTAGRAM_HANDOFF_CHAT_ID não está configurado no .env. '
                'Rode primeiro `python3 manage.py discover_handoff_chat_id`.',
            )

        once = options['once']
        client = TelegramClient(token=token)

        with _acquire_lock():
            self._install_signal_handlers()
            self.stdout.write(self.style.SUCCESS(
                f'Listener iniciado (allowed_chat_id={allowed_chat_id}, once={once}).',
            ))
            offset = _load_offset()

            while not _shutdown_requested():
                try:
                    updates = client.get_updates(
                        offset=offset,
                        timeout=POLL_TIMEOUT,
                        allowed_updates=['callback_query'],
                    )
                except TelegramClientError as exc:
                    log.warning('handoff_listener.get_updates_failed error=%s', exc)
                    self.stderr.write(self.style.WARNING(f'Erro getUpdates: {exc}'))
                    time.sleep(5)
                    if once:
                        break
                    continue

                for update in updates:
                    update_id = update.get('update_id')
                    if isinstance(update_id, int):
                        offset = update_id + 1
                        _persist_offset(offset)

                    callback = update.get('callback_query')
                    if not callback:
                        continue
                    self._handle_callback(client, callback, str(allowed_chat_id))

                if once:
                    break
                time.sleep(DEFAULT_LOOP_SLEEP)

            self.stdout.write('Listener encerrado.')

    def _handle_callback(self, client: TelegramClient, callback: dict, allowed_chat_id: str) -> None:
        callback_id = str(callback.get('id') or '')
        data = str(callback.get('data') or '')
        sender_id = (callback.get('from') or {}).get('id')
        if str(sender_id) != allowed_chat_id:
            log.warning(
                'handoff_listener.callback_rejected sender=%s allowed=%s data=%s',
                sender_id, allowed_chat_id, data,
            )
            if callback_id:
                try:
                    client.answer_callback_query(
                        callback_id,
                        text='Sem permissão.',
                        show_alert=True,
                    )
                except TelegramClientError:
                    pass
            return

        if not data.startswith(MARK_POSTED_CALLBACK_PREFIX):
            return

        try:
            post_id = int(data[len(MARK_POSTED_CALLBACK_PREFIX):])
        except ValueError:
            log.warning('handoff_listener.invalid_callback_data data=%s', data)
            return

        try:
            post = InstagramPost.objects.get(pk=post_id)
        except InstagramPost.DoesNotExist:
            log.warning('handoff_listener.post_not_found post_id=%s', post_id)
            if callback_id:
                try:
                    client.answer_callback_query(
                        callback_id,
                        text=f'Post #{post_id} não encontrado.',
                        show_alert=True,
                    )
                except TelegramClientError:
                    pass
            return

        already_posted = post.status == InstagramPost.Status.POSTED
        mark_post_as_posted(post, actor='telegram_callback')

        toast = (
            f'✅ Post #{post.id} já estava postado'
            if already_posted
            else f'✅ Post #{post.id} marcado como postado.'
        )
        if callback_id:
            try:
                client.answer_callback_query(callback_id, text=toast)
            except TelegramClientError as exc:
                log.warning('handoff_listener.answer_callback_failed error=%s', exc)

        self.stdout.write(self.style.SUCCESS(toast))

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, _request_shutdown)
        signal.signal(signal.SIGTERM, _request_shutdown)


_SHUTDOWN = {'requested': False}


def _request_shutdown(signum, frame) -> None:  # noqa: ARG001
    _SHUTDOWN['requested'] = True


def _shutdown_requested() -> bool:
    return _SHUTDOWN['requested']


def _load_offset() -> int | None:
    if not OFFSET_PATH.exists():
        return None
    try:
        raw = OFFSET_PATH.read_text().strip()
        return int(raw) if raw else None
    except (ValueError, OSError):
        return None


def _persist_offset(offset: int) -> None:
    try:
        OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        OFFSET_PATH.write_text(str(offset))
    except OSError as exc:
        log.warning('handoff_listener.offset_persist_failed error=%s', exc)


class _LockHeld(RuntimeError):
    pass


class _LockContext:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self):
        try:
            self.fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            try:
                existing_pid = self.path.read_text().strip() or '?'
            except OSError:
                existing_pid = '?'
            raise CommandError(
                f'Listener já em execução (lock {self.path}, pid={existing_pid}). '
                f'Se for órfão, apague o lock manualmente.',
            ) from None
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def _acquire_lock() -> _LockContext:
    return _LockContext(LOCK_PATH)
