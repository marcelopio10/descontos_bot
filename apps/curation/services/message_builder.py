from decimal import Decimal
import logging
import re
import textwrap

from apps.analytics.services.link_builder import build_referral_suffix, build_tracked_url
from apps.offers.models import Offer
from apps.distribution.models import SocialChannel

logger = logging.getLogger(__name__)

SEPARATOR = '············'
SPONSORED_PREFIX_RE = re.compile(
    r'^\s*an[uú]ncio\s+patrocinado\s*[\-–—:]\s*',
    flags=re.IGNORECASE,
)


def sanitize_offer_title(raw: str | None) -> str:
    cleaned = SPONSORED_PREFIX_RE.sub('', raw or '')
    return cleaned.strip()


def build_message(offer: Offer, channel: SocialChannel) -> str:
    final_url = get_final_url(offer, channel)
    original_price = offer.original_price or offer.current_price
    discount_pct = _format_percent_as_integer(offer.discount_pct)
    short_title = textwrap.shorten(
        sanitize_offer_title(offer.title) or 'Produto',
        width=80,
        placeholder='...',
    )
    badge = _build_badge(discount_pct)

    referral_suffix = build_referral_suffix(offer, channel)
    return (
        f'📦 *{short_title}*\n\n'
        f'{badge}\n'
        #f'{SEPARATOR}\n\n'
        f'💰 ~De {_format_brl(original_price)}~\n'
        f'✅ *Por apenas {_format_brl(offer.current_price)}*\n'
        f'🏷️ *{discount_pct}% OFF*\n\n'
        f'🛒 Compre aqui 👇\n'
        f'{final_url}\n\n'
        f'⏰ Oferta por tempo limitado!\n'
        f'{SEPARATOR}\n'
        f'🤖 @descontos.bot'
        f'{referral_suffix}'
    )


def _build_badge(discount_pct: int) -> str:
    if discount_pct >= 50:
        return '🚨 *OFERTA IMPERDÍVEL* 🚨'
    if discount_pct >= 30:
        return '🔥 *ALERTA DO BOT* 🔥'
    return '⚡ *BOT ACHOU DESCONTO* ⚡'


def build_offer_message(offer: Offer, channel: SocialChannel) -> str:
    return build_message(offer, channel)


def get_final_url(offer: Offer, channel: SocialChannel) -> str:
    final_url = build_tracked_url(offer, channel)
    logger.info(
        'whatsapp_link_resolved',
        extra={
            'offer_id': offer.id,
            'offer_slug': offer.slug,
            'marketplace': offer.marketplace.code,
            'channel_code': channel.code,
            'link_strategy': channel.link_strategy,
            'route': 'tracked',
            'final_url': final_url,
            'has_affiliate_tag': 'tag=' in (offer.affiliate_link or ''),
        },
    )
    return final_url


def _format_brl(value: Decimal) -> str:
    formatted = f'{value:,.2f}'
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _format_percent_as_integer(value: Decimal | None) -> int:
    if value is None:
        return 0
    return int(value.quantize(Decimal('1')))
