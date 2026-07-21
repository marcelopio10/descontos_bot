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
    badge = _build_badge(discount_pct, offer.id)
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
    return text


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


# Tarefa 5.3 (achado P9): o fallback antigo retornava sempre a MESMA frase fixa por
# categoria (e uma frase genérica única para qualquer título sem categoria reconhecida),
# o que fazia o mesmo clichê aparecer em dezenas de mensagens seguidas. Optamos por
# manter o highlight (não deixá-lo vazio) porque ele preenche um bloco visual do
# template que os usuários já esperam ver — mas com 3-4 variações por categoria.
# A escolha da variação usa `offer.id % len(variantes)`, não `random`: é determinística
# (mesma oferta sempre renderiza a mesma frase, útil para reprocessamento/testes) e varia
# entre ofertas diferentes o suficiente para quebrar o padrão repetitivo apontado no laudo.
_FALLBACK_HIGHLIGHT_VARIANTS: dict[str, tuple[str, ...]] = {
    'roupa_basica': (
        'boa opção para renovar peças básicas do dia a dia sem gastar muito.',
        'dá pra aproveitar para repor o guarda-roupa com preço mais em conta.',
        'preço bom para quem precisa trocar essas peças básicas.',
        'vale a pena para quem já tava adiando essa troca no guarda-roupa.',
    ),
    'suplemento': (
        'boa opção para quem já usa suplemento e quer repor o estoque.',
        'preço bom para quem já é da rotina de suplemento e precisa repor.',
        'dá pra aproveitar para deixar o estoque de suplemento em dia.',
    ),
    'utilidade_casa_externa': (
        'útil para casa, área externa ou viagens por ser portátil e fácil de guardar.',
        'prático para levar em viagem ou usar na área externa de casa.',
        'boa pedida para quem precisa de algo fácil de guardar e transportar.',
    ),
    'bebe': (
        'bom para deixar por perto na fase dos dentinhos.',
        'útil para ter à mão nessa fase do bebê.',
        'ajuda bastante nessa fase de dentição do bebê.',
    ),
}

_GENERIC_FALLBACK_HIGHLIGHT_VARIANTS: tuple[str, ...] = (
    'boa oportunidade para quem já estava procurando este tipo de produto.',
    'preço bom para quem já tava de olho nesse tipo de produto.',
    'vale a pena conferir se esse já era um item na sua lista.',
    'dá pra aproveitar se você já queria um produto desse.',
)


def _variant_index(seed: int | None, count: int) -> int:
    """Índice determinístico (não aleatório) de 0..count-1 a partir de um seed.

    Usar `offer.id` como seed garante que a MESMA oferta sempre produza a MESMA
    variação (reprodutível em reprocessamento e em teste), enquanto ofertas
    diferentes tendem a cair em índices diferentes.
    """
    if count <= 0:
        return 0
    return (seed or 0) % count


def _fallback_agent_highlight(offer: Offer) -> str:
    title = sanitize_offer_title(offer.title).lower()
    if any(term in title for term in ['camiseta', 'calça', 'bota', 'meia']):
        variants = _FALLBACK_HIGHLIGHT_VARIANTS['roupa_basica']
    elif any(term in title for term in ['creatina', 'beta alanina', 'suplemento']):
        variants = _FALLBACK_HIGHLIGHT_VARIANTS['suplemento']
    elif any(term in title for term in ['mesa', 'maleta', 'camping', 'jardim']):
        variants = _FALLBACK_HIGHLIGHT_VARIANTS['utilidade_casa_externa']
    elif any(term in title for term in ['mordedor', 'bebê', 'bebe']):
        variants = _FALLBACK_HIGHLIGHT_VARIANTS['bebe']
    else:
        variants = _GENERIC_FALLBACK_HIGHLIGHT_VARIANTS
    return variants[_variant_index(offer.id, len(variants))]


def _build_highlight_block(raw: str | None) -> str:
    text = ' '.join((raw or '').split())
    if not text:
        return ''
    text = textwrap.shorten(text, width=180, placeholder='...')
    return f'{text}\n\n'


# Tarefa 5.3 (achado P9): a faixa de badge era um texto fixo por nível de desconto
# ("⚡ BOT ACHOU DESCONTO ⚡" sempre para <30% OFF etc.), repetindo em toda mensagem
# de baixo desconto. Damos algumas variações por faixa (mantendo a faixa alta com
# o tom de urgência mais forte, mas também variada). `_select_badge_variant` é a
# fonte única de verdade do texto+índice para WhatsApp e Telegram: ambos os
# builders chamam a MESMA função (mesmo offer_id → mesmo índice → mesmo badge
# conceitual), só o formato de negrito muda (`*texto*` Markdown vs `<b>texto</b>` HTML).
BADGE_VARIANTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    'high': (
        ('🚨', 'OFERTA IMPERDÍVEL', '🚨'),
        ('💥', 'DESCONTÃO CONFIRMADO', '💥'),
        ('🔥', 'CORRE QUE ACABA', '🔥'),
    ),
    'mid': (
        ('🔥', 'ALERTA DO BOT', '🔥'),
        ('📉', 'PREÇO DESPENCOU', '📉'),
        ('🔥', 'BOT FLAGROU DESCONTO', '🔥'),
    ),
    'low': (
        ('⚡', 'BOT ACHOU DESCONTO', '⚡'),
        ('👀', 'BOT DE OLHO NESSA', '👀'),
        ('✅', 'VALE A PENA CONFERIR', '✅'),
        ('🔎', 'BOT GARIMPOU ESSA', '🔎'),
    ),
}


def _badge_tier(discount_pct: int) -> str:
    if discount_pct >= 50:
        return 'high'
    if discount_pct >= 30:
        return 'mid'
    return 'low'


def _select_badge_variant(discount_pct: int, offer_id: int | None) -> tuple[str, str, str]:
    """Retorna (emoji_esquerda, texto, emoji_direita) para a faixa de desconto.

    Compartilhado entre `message_builder.py` (WhatsApp) e `telegram_message_builder.py`
    para garantir o mesmo critério/índice de variação nos dois canais.
    """
    variants = BADGE_VARIANTS[_badge_tier(discount_pct)]
    return variants[_variant_index(offer_id, len(variants))]


def _build_badge(discount_pct: int, offer_id: int | None = None) -> str:
    lead, label, trail = _select_badge_variant(discount_pct, offer_id)
    return f'{lead} *{label}* {trail}'


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
