from decimal import Decimal
import textwrap

from apps.offers.models import Offer


def build_offer_message(offer: Offer) -> str:
    final_url = get_final_url(offer)
    original_price = offer.original_price or offer.current_price
    discount_pct = _format_percent_as_integer(offer.discount_pct)
    short_title = textwrap.shorten(
        offer.title.strip() or 'Produto',
        width=80,
        placeholder='...',
    )

    return (
        f'📦 *{short_title}*\n\n'
        f'{_build_badge(discount_pct)}\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n\n'
        f'💰 ~De {_format_brl(original_price)}~\n'
        f'✅ *Por apenas {_format_brl(offer.current_price)}*\n'
        f'🏷️ *{discount_pct}% OFF*\n\n'
        f'🛒 Compre aqui 👇\n'
        f'{final_url}\n\n'
        f'⏰ Oferta por tempo limitado!\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'🤖 @descontos.bot'
    )


def get_final_url(offer: Offer) -> str:
    return offer.affiliate_url or offer.product_url


def _build_badge(discount_pct: int) -> str:
    if discount_pct >= 50:
        return '🚨 *OFERTA IMPERDÍVEL* 🚨'
    if discount_pct >= 30:
        return '🔥 *ALERTA DO BOT* 🔥'
    return '⚡ *BOT ACHOU DESCONTO* ⚡'


def _format_brl(value: Decimal) -> str:
    formatted = f'{value:,.2f}'
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _format_percent_as_integer(value: Decimal | None) -> int:
    if value is None:
        return 0
    return int(value.quantize(Decimal('1')))
