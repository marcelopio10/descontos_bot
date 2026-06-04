import logging
from dataclasses import dataclass
from datetime import datetime, time as time_obj
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.distribution.services.telegram_client import (
    TelegramClient,
    TelegramClientError,
)
from apps.social_posts.models import InstagramPost


log = logging.getLogger(__name__)

MARK_POSTED_CALLBACK_PREFIX = 'posted:'
TELEGRAM_CAPTION_LIMIT = 1024


class HandoffDisabled(RuntimeError):
    pass


class HandoffError(RuntimeError):
    pass


@dataclass(frozen=True)
class HandoffResult:
    document_message_id: str
    text_message_id: str
    skipped: bool = False
    reason: str = ''


def deliver_post_to_handoff(post: InstagramPost) -> HandoffResult:
    """Entrega o pacote do story (PNG + caption + URL do sticker) no DM Telegram.

    Idempotente: se `telegram_handoff_message_id` já estiver preenchido, não
    reentrega. Para forçar reenvio, limpe esse campo antes de chamar.
    """
    token = getattr(settings, 'INSTAGRAM_HANDOFF_BOT_TOKEN', '')
    chat_id = getattr(settings, 'INSTAGRAM_HANDOFF_CHAT_ID', '')
    if not token or not chat_id:
        raise HandoffDisabled(
            'Handoff Telegram não configurado (INSTAGRAM_HANDOFF_BOT_TOKEN/CHAT_ID ausentes).',
        )

    if post.telegram_handoff_message_id:
        return HandoffResult(
            document_message_id=post.telegram_handoff_message_id,
            text_message_id='',
            skipped=True,
            reason='já entregue anteriormente',
        )

    asset_path = _resolve_asset_path(post)
    sticker_url = post.sticker_target_url or ''
    quiet = _is_quiet_now()

    client = TelegramClient(token=token)

    short_caption = (
        f'📸 Story #{post.id} pronto pra publicar'
        '\n\nCaption completa e link do sticker chegam na próxima mensagem.'
    )
    if len(short_caption) > TELEGRAM_CAPTION_LIMIT:
        short_caption = short_caption[: TELEGRAM_CAPTION_LIMIT - 1] + '…'

    try:
        doc_result = client.send_document(
            chat_id=chat_id,
            document_path=asset_path,
            caption_html=short_caption,
            disable_notification=quiet,
        )
    except TelegramClientError as exc:
        raise HandoffError(f'Falha ao enviar PNG: {exc}') from exc

    if not doc_result.success:
        raise HandoffError(f'Falha ao enviar PNG: {doc_result.error_message}')

    text_html = _build_handoff_message(post, sticker_url)
    keyboard = [
        [
            {
                'text': '✅ Marcar como postado',
                'callback_data': f'{MARK_POSTED_CALLBACK_PREFIX}{post.id}',
            },
        ],
    ]

    try:
        text_result = client.send_message(
            chat_id=chat_id,
            text_html=text_html,
            inline_keyboard=keyboard,
            disable_notification=quiet,
        )
    except TelegramClientError as exc:
        raise HandoffError(
            f'PNG enviado mas falhou ao mandar caption (msg id PNG={doc_result.message_id}): {exc}',
        ) from exc

    if not text_result.success:
        raise HandoffError(
            f'PNG enviado mas falhou ao mandar caption: {text_result.error_message}',
        )

    post.telegram_handoff_message_id = text_result.message_id
    post.status = InstagramPost.Status.AWAITING_POST
    post.published_error = ''
    post.save(
        update_fields=[
            'telegram_handoff_message_id',
            'status',
            'published_error',
            'updated_at',
        ],
    )

    return HandoffResult(
        document_message_id=doc_result.message_id,
        text_message_id=text_result.message_id,
    )


def mark_post_as_posted(
    post: InstagramPost,
    *,
    actor: str = 'telegram_callback',
) -> InstagramPost:
    """Marca post como postado a partir de uma confirmação manual.

    Idempotente — se já estiver `posted`, mantém o estado e retorna.
    Edita o botão da mensagem do handoff (se houver) pra evitar clique duplicado.
    """
    if post.status == InstagramPost.Status.POSTED:
        return post

    post.status = InstagramPost.Status.POSTED
    post.posted_at = timezone.now()
    post.published_error = ''
    post.save(
        update_fields=['status', 'posted_at', 'published_error', 'updated_at'],
    )

    log.info(
        'instagram_handoff.post_marked_posted post_id=%s actor=%s',
        post.id, actor,
    )

    if post.telegram_handoff_message_id:
        token = getattr(settings, 'INSTAGRAM_HANDOFF_BOT_TOKEN', '')
        chat_id = getattr(settings, 'INSTAGRAM_HANDOFF_CHAT_ID', '')
        if token and chat_id:
            try:
                client = TelegramClient(token=token)
                client.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=post.telegram_handoff_message_id,
                    inline_keyboard=[
                        [
                            {
                                'text': '✅ Postado',
                                'callback_data': 'noop',
                            },
                        ],
                    ],
                )
            except (TelegramClientError, Exception) as exc:
                log.warning(
                    'instagram_handoff.edit_markup_failed post_id=%s error=%s',
                    post.id, exc,
                )

    return post


def _build_handoff_message(post: InstagramPost, sticker_url: str) -> str:
    sticker_block = (
        f'\n\n🔗 <b>URL DO STICKER</b> (NÃO ESQUEÇA DE COLAR NO STORY):\n'
        f'<code>{sticker_url}</code>'
        if sticker_url
        else '\n\n⚠️ Post sem URL de sticker — verifique <code>sticker_target_url</code>.'
    )
    caption = post.caption or '(sem caption)'
    return (
        f'<b>Story #{post.id}</b>\n\n'
        f'<b>Caption pronta:</b>\n<pre>{_escape_html(caption)}</pre>'
        f'{sticker_block}'
    )


def _escape_html(text: str) -> str:
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def _resolve_asset_path(post: InstagramPost) -> Path:
    if not post.asset_paths:
        raise HandoffError(f'Post #{post.id} sem asset_paths.')
    raw = post.asset_paths[0]
    path = Path(raw)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    if not path.exists():
        raise HandoffError(f'Asset não existe no disco: {path}')
    return path


def _is_quiet_now() -> bool:
    raw = getattr(settings, 'INSTAGRAM_HANDOFF_QUIET_HOURS_BRT', '')
    if not raw:
        return False
    try:
        start_str, end_str = raw.split('-', 1)
        start = _parse_hhmm(start_str.strip())
        end = _parse_hhmm(end_str.strip())
    except ValueError:
        log.warning('instagram_handoff.invalid_quiet_hours raw=%s', raw)
        return False

    tz_name = getattr(settings, 'INSTAGRAM_TIMEZONE', 'America/Sao_Paulo')
    now_local = datetime.now(ZoneInfo(tz_name)).time()
    if start <= end:
        return start <= now_local < end
    # Janela cruza meia-noite (ex.: 22:00-08:00).
    return now_local >= start or now_local < end


def _parse_hhmm(raw: str) -> time_obj:
    hh, mm = raw.split(':', 1)
    return time_obj(int(hh), int(mm))
