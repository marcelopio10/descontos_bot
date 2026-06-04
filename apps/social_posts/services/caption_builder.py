from decimal import Decimal

from apps.offers.models import Offer


DISCLOSURE = 'Como Associado da Amazon, ganho por compras qualificadas.'
HASHTAGS = '#ofertas #descontos #achadinhos #amazonbrasil #descontosbot'

GROUP_CTA_WHATSAPP = (
    '💬 Recebe ofertas em primeira mão no nosso WhatsApp\n'
    '👉 Link na bio descontos.bot/links'
)
GROUP_CTA_TELEGRAM = (
    '💬 Recebe ofertas em primeira mão no nosso Telegram\n'
    '👉 Link na bio descontos.bot/links'
)


def build_caption(offer: Offer, *, group_cta: str = 'whatsapp') -> str:
    lines = [
        'Oferta monitorada pelo descontos.bot',
        '',
        offer.title,
        f'Por R$ {_format_money(offer.current_price)}',
    ]

    if offer.original_price:
        lines.append(f'De R$ {_format_money(offer.original_price)}')
    if offer.discount_pct:
        lines.append(f'Desconto: {_format_decimal(offer.discount_pct)}%')

    cta = GROUP_CTA_TELEGRAM if group_cta == 'telegram' else GROUP_CTA_WHATSAPP
    lines.extend(
        [
            '',
            cta,
            '',
            DISCLOSURE,
            HASHTAGS,
        ],
    )
    return '\n'.join(lines)


def _format_money(value: Decimal) -> str:
    return _format_decimal(value)


def _format_decimal(value: Decimal) -> str:
    return f'{value:.2f}'.replace('.', ',')
