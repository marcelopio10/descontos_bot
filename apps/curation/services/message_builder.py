from decimal import Decimal
import logging
import re
import textwrap

from apps.analytics.services.link_builder import build_referral_suffix, build_tracked_url
from apps.curation.services.ad_disclosure import ad_disclosure_prefix
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
    return _build_offer_template(offer, channel, title=offer.title)


def _build_offer_template(
    offer: Offer,
    channel: SocialChannel,
    *,
    title: str | None = None,
    highlight: str | None = None,
) -> str:
    final_url = get_final_url(offer, channel)
    original_price = offer.original_price or offer.current_price
    discount_pct = _format_percent_as_integer(offer.discount_pct)
    short_title = textwrap.shorten(
        sanitize_offer_title(title or offer.title) or 'Produto',
        width=80,
        placeholder='...',
    )
    badge = _build_badge(discount_pct)
    highlight_block = _build_highlight_block(highlight)

    referral_suffix = build_referral_suffix(offer, channel)
    disclosure = ad_disclosure_prefix(offer.marketplace.code)
    return (
        f'{disclosure}'
        f'📦 *{short_title}*\n\n'
        f'{badge}\n'
        f'{highlight_block}'
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


def build_curated_offer_message(item, channel: SocialChannel) -> str:
    """Preserve the WhatsApp sales template while applying curated title.

    The AI caption is editorial input, not a full message replacement: replacing
    the template removes price hierarchy, CTA link and footer, making homolog
    messages less attractive and less trackable.
    """
    title = item.final_title or item.decision.title_rewritten or item.offer.title
    highlight = _build_agent_highlight(item)
    return _build_offer_template(item.offer, channel, title=title, highlight=highlight)


def _build_agent_highlight(item, raw: str | None = None) -> str:
    raw = raw if raw is not None else (item.final_caption_whatsapp or item.decision.caption_rewritten or '')
    text = _clean_agent_highlight_text(raw, item.offer)
    if not text:
        text = _fallback_agent_highlight(item.offer)
    return f'🤖 Trecho do agente descontos-bot: {text}'


def _clean_agent_highlight_text(raw: str | None, offer: Offer) -> str:
    text = ' '.join((raw or '').split())
    if not text:
        return ''

    text = re.sub(r'^✨\s*', '', text).strip()
    text = re.sub(r'^🤖\s*Trecho do agente descontos-bot\s*[:\-–—]?\s*', '', text, flags=re.IGNORECASE).strip()
    if re.search(r'Curadoria destacou a oportunidade\s+(?:pelo|por)\s+preço\s+e\s+desconto', text, flags=re.IGNORECASE):
        return ''
    text = SPONSORED_PREFIX_RE.sub('', text).strip()
    text = re.sub(r'\bpor\s+R\$\s*\d+[\d\.]*,\d{2}\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:com\s+)?\d+%\s*OFF\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bCuradoria destacou a oportunidade\s+(?:pelo|por)\s+preço\s+e\s+desconto(?:\s+do\s+marketplace\s+[^.]+)?\.?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\bpreço\s+e\s+desconto\b', 'contexto de uso', text, flags=re.IGNORECASE)
    text = _remove_title_fragments(text, offer.title)
    text = re.sub(r'\s+([,.])', r'\1', text)
    text = re.sub(r'\s{2,}', ' ', text).strip(' -–—,.')
    return text


def _remove_title_fragments(text: str, title: str | None) -> str:
    words = [word for word in re.findall(r'[\wÀ-ÿ]+', sanitize_offer_title(title)) if len(word) >= 4]
    stopwords = {
        'para', 'com', 'sem', 'preta', 'branca', 'masculina', 'feminina', 'infantil',
        'premium', 'anuncio', 'patrocinado', 'curta', 'lisa', 'algodao', 'manga',
    }
    keywords = [re.escape(word) for word in words if word.lower() not in stopwords]
    if not keywords:
        return text
    pattern = r'\b(?:' + '|'.join(keywords[:10]) + r')\b'
    text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', text).strip()


def _fallback_agent_highlight(offer: Offer) -> str:
    title = sanitize_offer_title(offer.title).lower()
    if any(term in title for term in ['camiseta', 'calça', 'bota', 'meia']):
        return 'boa opção para renovar peças básicas do dia a dia sem gastar muito.'
    if any(term in title for term in ['creatina', 'beta alanina', 'suplemento']):
        return 'boa opção para quem já usa suplemento e quer repor o estoque.'
    if any(term in title for term in ['mesa', 'maleta', 'camping', 'jardim']):
        return 'útil para casa, área externa ou viagens por ser portátil e fácil de guardar.'
    if any(term in title for term in ['mordedor', 'bebê', 'bebe']):
        return 'item prático para rotina com bebê, com apelo de uso diário.'
    return 'boa oportunidade para quem já estava procurando este tipo de produto.'


def _build_highlight_block(raw: str | None) -> str:
    text = ' '.join((raw or '').split())
    if not text:
        return ''
    text = textwrap.shorten(text, width=180, placeholder='...')
    return f'✨ {text}\n\n'


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
