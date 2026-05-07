from decimal import Decimal
import textwrap

from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


def build_message(offer: Offer, channel: SocialChannel) -> str:
    final_url = get_final_url(offer, channel)
    original_price = offer.original_price or offer.current_price
    discount_pct = _format_percent_as_integer(offer.discount_pct)
    short_title = textwrap.shorten(
        offer.title.strip() or 'Produto',
        width=80,
        placeholder='...',
    )

    return (
        f'Achei essa oferta aqui:\n\n'
        f'{short_title}\n\n'
        f'De: {_format_brl(original_price)}\n'
        f'Por: {_format_brl(offer.current_price)}\n'
        f'Desconto: {discount_pct}%\n\n'
        f'Link:\n'
        f'{final_url}'
    )


def build_offer_message(offer: Offer, channel: SocialChannel) -> str:
    return build_message(offer, channel)


def get_final_url(offer: Offer, channel: SocialChannel) -> str:
    if channel.link_strategy == SocialChannel.LinkStrategy.AFFILIATE_DIRECT:
        return offer.affiliate_link
    return offer.bridge_url


def _format_brl(value: Decimal) -> str:
    formatted = f'{value:,.2f}'
    formatted = formatted.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'R$ {formatted}'


def _format_percent_as_integer(value: Decimal | None) -> int:
    if value is None:
        return 0
    return int(value.quantize(Decimal('1')))
