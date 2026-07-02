from dataclasses import dataclass
from decimal import Decimal
from html import escape
import textwrap

from django.conf import settings

from apps.curation.services.ad_disclosure import ad_disclosure_prefix
from apps.curation.services.message_builder import get_final_url, sanitize_offer_title
from apps.curation.models import CuratedBatchItem
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


SEPARATOR = '············'
CAPTION_MAX = 1024
MESSAGE_MAX = 4096
MIN_TITLE_WIDTH = 30
DEFAULT_TITLE_WIDTH = 80
TITLE_SHRINK_STEP = 10


@dataclass(frozen=True)
class TelegramMessagePayload:
    caption: str
    inline_keyboard: list[list[dict]]
    final_url: str
    use_photo: bool
    photo_url: str


def build_telegram_payload(
    offer: Offer,
    channel: SocialChannel,
) -> TelegramMessagePayload:
    final_url = get_final_url(offer, channel)
    photo_url = (offer.image_url or '').strip()
    use_photo = bool(photo_url and photo_url.lower().startswith('https://'))
    max_len = CAPTION_MAX if use_photo else MESSAGE_MAX

    caption = _build_caption(offer, max_len)
    if use_photo and len(caption) > CAPTION_MAX:
        use_photo = False
        caption = _build_caption(offer, MESSAGE_MAX)

    keyboard = [[{'text': '🛒 Comprar agora', 'url': final_url}]]
    return TelegramMessagePayload(
        caption=caption,
        inline_keyboard=keyboard,
        final_url=final_url,
        use_photo=use_photo,
        photo_url=photo_url if use_photo else '',
    )


def build_curated_telegram_payload(
    item: CuratedBatchItem,
    channel: SocialChannel,
) -> TelegramMessagePayload:
    offer = item.offer
    final_url = get_final_url(offer, channel)
    raw_caption = (item.final_caption_telegram or item.final_title or offer.title or 'Oferta curada').strip()
    caption = _sanitize_curated_caption(raw_caption, CAPTION_MAX)
    photo_url = (item.local_image_path or item.final_image_url or offer.image_url or '').strip()
    use_photo = bool(photo_url)
    keyboard = [[{'text': '🛒 Comprar agora', 'url': final_url}]]
    return TelegramMessagePayload(
        caption=caption,
        inline_keyboard=keyboard,
        final_url=final_url,
        use_photo=use_photo,
        photo_url=photo_url if use_photo else '',
    )


def _sanitize_curated_caption(raw_caption: str, max_len: int) -> str:
    caption = escape(raw_caption.strip())
    if len(caption) <= max_len:
        return caption
    return caption[: max(0, max_len - 1)].rstrip() + '…'


def _build_caption(offer: Offer, max_len: int) -> str:
    width = DEFAULT_TITLE_WIDTH
    while True:
        caption = _render(offer, width)
        if len(caption) <= max_len or width <= MIN_TITLE_WIDTH:
            return caption
        width -= TITLE_SHRINK_STEP


def _render(offer: Offer, title_width: int) -> str:
    short_title = textwrap.shorten(
        sanitize_offer_title(offer.title) or 'Produto',
        width=max(title_width, MIN_TITLE_WIDTH),
        placeholder='...',
    )
    original_price = offer.original_price or offer.current_price
    discount_pct = _format_percent_as_integer(offer.discount_pct)
    badge = _build_badge(discount_pct)
    disclosure = getattr(
        settings,
        'TELEGRAM_DISCLOSURE_MESSAGE',
        'Como Associado da Amazon, ganho por compras qualificadas.',
    )

    disclosure = ad_disclosure_prefix(offer.marketplace.code)
    disclosure_footer = f'<i>{escape(disclosure)}</i>\n' if disclosure else ''
    return (
        f'{disclosure}'
        f'<b>📦 {escape(short_title)}</b>\n\n'
        f'{badge}\n\n'
        f'💰 <s>De {_format_brl(original_price)}</s>\n'
        f'✅ <b>Por apenas {_format_brl(offer.current_price)}</b>\n'
        f'🏷️ <b>{discount_pct}% OFF</b>\n\n'
        f'⏰ Oferta por tempo limitado!\n'
        f'{SEPARATOR}\n'
        f'{disclosure_footer}'
        f'🤖 @descontosbotlgm'
    )


def _build_badge(discount_pct: int) -> str:
    if discount_pct >= 50:
        return '🚨 <b>OFERTA IMPERDÍVEL</b> 🚨'
    if discount_pct >= 30:
        return '🔥 <b>ALERTA DO BOT</b> 🔥'
    return '⚡ <b>BOT ACHOU DESCONTO</b> ⚡'


def _format_brl(value: Decimal) -> str:
    formatted = f'{value:,.2f}'
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _format_percent_as_integer(value: Decimal | None) -> int:
    if value is None:
        return 0
    return int(value.quantize(Decimal('1')))
