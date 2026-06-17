import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Marketplace detection (P1-5: mais players brasileiros)
# ---------------------------------------------------------------------------
MARKETPLACE_DOMAINS = {
    'amazon': ('amazon.', 'amzn.to'),
    'mercadolivre': ('mercadolivre.', 'mercadolivre.com', 'meli.la'),
    'shopee': ('shopee.',),
    'magalu': ('magazineluiza.', 'magalu.'),
    'aliexpress': ('aliexpress.',),
    'shein': ('shein.',),
    'americanas': ('americanas.',),
    'casas_bahia': ('casasbahia.', 'casasbahia.com.br'),
    'centauro': ('centauro.',),
    'netshoes': ('netshoes.',),
    'kabum': ('kabum.',),
}

# ---------------------------------------------------------------------------
# Category keywords
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    'casa/cozinha': ('air fryer', 'panela', 'cafeteira', 'cozinha', 'fogao', 'geladeira', 'microondas', 'aspirador'),
    'moda': ('tenis', 'camiseta', 'calca', 'vestido', 'sapato', 'bolsa', 'jaqueta', 'moletom'),
    'tecnologia': ('notebook', 'monitor', 'fone', 'carregador', 'ssd', 'celular', 'tablet', 'iphone', 'smartphone', 'gabinete', 'placa de video', 'processador', 'mouse', 'teclado'),
    'beleza': ('perfume', 'creme', 'shampoo', 'maquiagem', 'hidratante', 'protetor solar'),
    'esporte': ('bicicleta', 'esteira', 'halter', 'camiseta tech', 'legging'),
    'brinquedos': ('lego', 'boneco', 'carrinho', 'pelucia'),
    'pet': ('racao', 'pet', 'gato', 'cachorro'),
}

# ---------------------------------------------------------------------------
# Brand detection (P1-6)
# ---------------------------------------------------------------------------
BRAND_PATTERNS = (
    'nike', 'adidas', 'olympikus', 'asics', 'mizuno', 'puma', 'new balance',
    'samsung', 'apple', 'xiaomi', 'motorola', 'lg', 'sony', 'brastemp',
    'consul', 'electrolux', 'philco', 'mondial', 'cadence', 'arno',
    'lenovo', 'dell', 'acer', 'positivo', 'multilaser',
)

# ---------------------------------------------------------------------------
# Urgency / proof / CTA terms
# ---------------------------------------------------------------------------
URGENCY_TERMS = ('corre', 'acabando', 'relampago', 'só hoje', 'so hoje', 'ultimas unidades', 'últimas unidades')
PROOF_TERMS = ('muito vendido', 'bem avaliado', 'viral', 'campeao', 'campeão', 'mais vendido', 'best seller')

CTA_TERMS = {
    'corre': 'corre',
    'garante_ja': ('garante ja', 'garante já', 'garantir'),
    'acabando': 'acabando',
    'ultimas_unidades': ('ultimas unidades', 'últimas unidades'),
    'so_hoje': ('só hoje', 'so hoje'),
    'corra': 'corra',
    'nao_perca': ('não perca', 'nao perca'),
    'aproveite': 'aproveite',
}

# ---------------------------------------------------------------------------
# Programas de entrega
# ---------------------------------------------------------------------------
DELIVERY_PROGRAM_TERMS = {
    'full': ('full',),
    'prime': ('prime',),
    'frete_gratis': ('frete gratis', 'frete grátis', 'frete grátis acima', 'frete gratis acima'),
}

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
PRICE_RE = re.compile(r'R\$\s*([0-9\.]+,\d{2}|[0-9]+(?:[\.,]\d{2})?)', re.IGNORECASE)
COUPON_RE = re.compile(
    r'\b(?:(?:cupom)\s*[:=\-]?\s*|(?:use|aplique)\s+(?:o\s+)?(?:cupom\s+)?)([A-Z0-9][A-Z0-9_-]{2,20})\b',
    re.IGNORECASE,
)
URL_RE = re.compile(r'https?://[^\s)\]}>"\']+', re.IGNORECASE)

# Pix discount patterns: "5% de desconto no Pix", "Pix com 10% de desconto", "5% off no Pix"
PIX_DISCOUNT_PCT_RE = re.compile(
    r'(\d{1,3})\s*%\s*(?:de\s+)?(?:desconto|off)\s+(?:no|na)\s+(?:pix|PIX)'
    r'|(?:pix|PIX)\s+(?:com\s+)?(?:desconto\s+)?(\d{1,3})\s*%'
    r'|(\d{1,3})\s*%\s+(?:no|na)\s+(?:pix|PIX)',
    re.IGNORECASE,
)
PIX_GENERIC_RE = re.compile(r'(?:desconto|off|desconto\s+de)\s+.*?\s+(?:no|na)\s+(?:pix|PIX)|(?:pix|PIX)\s+(?:com|dá|da|com\s+desconto)|(?:pix|PIX)', re.IGNORECASE)

# Installment patterns: "12x de R$ 99,90", "10x s/ juros", "3x sem juros"
PARCELAMENTO_RE = re.compile(r'(\d{1,2})x\s+(?:de\s+)?(?:R\$\s*[0-9.,]+)?\s*(?:s/?\s*juros|sem\s+juros)?', re.IGNORECASE)
PARCELADO_SEM_JUROS_RE = re.compile(r'\d{1,2}x\s+(?:de\s+)?(?:R\$\s*[0-9.,]+)?\s*(?:s/?\s*juros|sem\s+juros)', re.IGNORECASE)

# Cashback patterns: "5% de cashback", "cashback de R$ 20"
CASHBACK_RE = re.compile(r'cashback', re.IGNORECASE)
CASHBACK_PCT_RE = re.compile(r'(\d{1,3})[%\%]\s+(?:de\s+)?cashback', re.IGNORECASE)
CASHBACK_VALUE_RE = re.compile(r'cashback\s+(?:de\s+)?R\$\s*([0-9\.]+,\d{2})', re.IGNORECASE)

# Menor preço patterns
MENOR_PRECO_RE = re.compile(r'menor\s+pre[cç]o|pre[cç]o\s+hist[oó]rico|mais\s+barato', re.IGNORECASE)

# Coupon type detection
COUPON_PCT_RE = re.compile(r'(\d{1,3})%\s+(?:off|desconto)', re.IGNORECASE)
COUPON_VALUE_RE = re.compile(r'R\$\s*([0-9\.]+,\d{2})\s+(?:off|desconto)', re.IGNORECASE)
COUPON_FRETE_RE = re.compile(r'frete\s+gr[aá]tis', re.IGNORECASE)

# Headline patterns (first line is uppercase or has emoji prefix)
HEADLINE_RE = re.compile(r'^[*\[\(🔥🛒⚡💰🎁👟📱💻🎯‼️💥‼🚨]{1,3}\s*\S')

# De/Por pattern
DE_POR_RE = re.compile(r'\bDe\s+R\$', re.IGNORECASE)

# Bold markdown: *text*
NEGRITO_RE = re.compile(r'\*[^*]+\*')

# Emoji detection — individual character class (no + quantifier)
EMOJI_CHAR_RE = re.compile(
    '['
    '\U0001F600-\U0001F64F'  # emoticons
    '\U0001F300-\U0001F5FF'  # symbols & pictographs
    '\U0001F680-\U0001F6FF'  # transport & map
    '\U0001F1E0-\U0001F1FF'  # flags
    '\U00002702-\U000027B0'  # dingbats
    '\U000024C2-\U0001F251'
    '\U0001f926-\U0001f937'
    '\U00010000-\U0010ffff'
    '\u2640-\u2642'
    '\u2600-\u2B55'
    '\u200d\u23cf\u23e9\u231a\ufe0f\u3030'
    ']',
    re.UNICODE,
)

# Caixa alta: >70% alpha chars are uppercase
UPPERCASE_RATIO = 0.70


def parse_observed_message(text: str, has_image: bool = False, urls: list[str] | None = None) -> dict:
    urls = urls or URL_RE.findall(text or '')
    normalized = _normalize_text(text or '')
    prices = [_parse_price(match) for match in PRICE_RE.findall(text or '')]
    prices = [price for price in prices if price is not None]
    original_price = prices[0] if len(prices) >= 2 else None
    price = prices[-1] if prices else None
    discount_pct = _discount_pct(original_price, price)
    coupon = _extract_coupon(text or '')
    coupon_tipo = _classify_coupon(text or '', coupon)
    labels = _labels(normalized, price, discount_pct, coupon, has_image, text or '')
    category = _category(normalized)
    hints = _scraper_hints(category, price, discount_pct, normalized)

    # P0-2: Price mechanics
    parcelamento_match = PARCELAMENTO_RE.search(text or '')
    parcelamento = int(parcelamento_match.group(1)) if parcelamento_match else None
    parcelado_sem_juros = bool(PARCELADO_SEM_JUROS_RE.search(text or '')) if parcelamento else None
    pix_match = PIX_DISCOUNT_PCT_RE.search(text or '')
    pix = bool(PIX_GENERIC_RE.search(text or '')) or bool(pix_match)
    pix_desconto_pct = None
    if pix_match:
        pct_str = next((g for g in pix_match.groups() if g is not None), None)
        if pct_str:
            try:
                pix_desconto_pct = Decimal(pct_str).quantize(Decimal('0.01'))
            except (InvalidOperation, ValueError):
                pass
    cashback = bool(CASHBACK_RE.search(text or ''))
    cashback_valor = _extract_cashback_value(text or '') if cashback else None
    menor_preco = bool(MENOR_PRECO_RE.search(text or ''))

    # P0-3: Copy and format patterns
    plain_text = text or ''
    emoji_densidade = _emoji_density(plain_text)
    emojis_top = _top_emojis(plain_text)
    tem_headline = _detect_headline(plain_text)
    tem_de_por = bool(DE_POR_RE.search(plain_text))
    tem_cta, cta_termos = _detect_cta(normalized)
    tipo_midia = _classify_media(has_image, plain_text)
    tamanho_mensagem = len(plain_text)
    usa_caixa_alta = _detect_uppercase(plain_text)
    usa_negrito = bool(NEGRITO_RE.search(plain_text))

    # P1-5: Marketplace richer
    marketplace, dominio_desconhecido = _marketplace_with_domain(urls)
    programa_entrega = _detect_delivery_program(normalized)

    # P1-6: Brand
    marca = _extract_brand(normalized)

    # P1-4: timing fields are derived from sent_at in reports, not stored here

    return {
        # v1 fields (unchanged)
        'marketplace': marketplace,
        'price': _decimal_to_str(price),
        'original_price': _decimal_to_str(original_price),
        'discount_pct': _decimal_to_str(discount_pct),
        'coupon': coupon,
        'labels': labels,
        'category': category,
        'scraper_hints': hints,
        # P0-2: Price mechanics
        'parcelamento': parcelamento,
        'parcelado_sem_juros': parcelado_sem_juros,
        'pix': pix if pix else None,
        'pix_desconto_pct': _decimal_to_str(pix_desconto_pct) if pix_desconto_pct else '',
        'cashback': cashback if cashback else None,
        'cashback_valor': _decimal_to_str(cashback_valor) if cashback_valor else '',
        'menor_preco': menor_preco if menor_preco else None,
        'cupom_tipo': coupon_tipo,
        # P0-3: Copy and format
        'emoji_densidade': float(emoji_densidade) if emoji_densidade is not None else None,
        'emojis_top': emojis_top,
        'tem_headline': tem_headline,
        'tem_de_por': tem_de_por if tem_de_por else None,
        'tem_cta': tem_cta if tem_cta else None,
        'cta_termos': cta_termos,
        'tipo_midia': tipo_midia,
        'tamanho_mensagem': tamanho_mensagem,
        'usa_caixa_alta': usa_caixa_alta if usa_caixa_alta is not None else None,
        'usa_negrito': usa_negrito if usa_negrito else None,
        # P1-5: Marketplace richer
        'marketplace_dominio_desconhecido': dominio_desconhecido,
        'programa_entrega': programa_entrega,
        # P1-6: Brand
        'marca': marca,
    }


# ---------------------------------------------------------------------------
# v1 extraction helpers (unchanged)
# ---------------------------------------------------------------------------

def _parse_price(raw: str) -> Decimal | None:
    value = raw.replace('.', '').replace(',', '.')
    try:
        return Decimal(value).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _discount_pct(original: Decimal | None, current: Decimal | None) -> Decimal | None:
    if not original or not current or original <= 0 or current >= original:
        return None
    return (((original - current) / original) * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _decimal_to_str(value: Decimal | None) -> str:
    return str(value) if value is not None else ''


def _extract_coupon(text: str) -> str:
    match = COUPON_RE.search(text)
    return match.group(1).upper() if match else ''


def _labels(normalized: str, price: Decimal | None, discount_pct: Decimal | None, coupon: str, has_image: bool, raw_text: str = '') -> list[str]:
    labels: list[str] = []
    if any(term in normalized for term in URGENCY_TERMS):
        labels.append('urgencia')
    if any(term in normalized for term in PROOF_TERMS):
        labels.append('prova_social')
    if coupon:
        labels.append('cupom')
    if has_image:
        labels.append('imagem')
    # Price ranges (v1)
    if price is not None:
        if price <= Decimal('50'):
            labels.append('ate_50')
        elif price <= Decimal('100'):
            labels.append('ate_100')
        elif price <= Decimal('300'):
            labels.append('ate_300')
        else:
            labels.append('acima_300')
    # P0-2: Discount depth labels
    if discount_pct is not None:
        if discount_pct >= Decimal('70'):
            labels.append('desconto_70')
        if discount_pct >= Decimal('50'):
            labels.append('desconto_50')
        if discount_pct >= Decimal('30'):
            labels.append('desconto_30')
    # P0-2: Price mechanic labels
    if PARCELADO_SEM_JUROS_RE.search(raw_text):
        labels.append('parcelado_sem_juros')
    if PIX_GENERIC_RE.search(raw_text) or PIX_DISCOUNT_PCT_RE.search(raw_text):
        labels.append('pix')
    if CASHBACK_RE.search(raw_text):
        labels.append('cashback')
    if MENOR_PRECO_RE.search(raw_text):
        labels.append('menor_preco')
    if COUPON_FRETE_RE.search(raw_text):
        labels.append('frete_gratis')
    return labels


def _category(normalized: str) -> str:
    for category, terms in CATEGORY_KEYWORDS.items():
        if any(term in normalized for term in terms):
            return category
    return ''


def _scraper_hints(category: str, price: Decimal | None, discount_pct: Decimal | None = None, normalized: str = '') -> list[str]:
    hints: list[str] = []
    if category:
        hints.append(f'categoria:{category}')
    for term in ('air fryer', 'cafeteira', 'fone', 'monitor', 'tenis'):
        if term in normalized:
            hints.append(f'termo:{term}')
    if price is not None:
        if price <= Decimal('100'):
            hints.append('faixa_preco:ate_100')
        elif price <= Decimal('300'):
            hints.append('faixa_preco:ate_300')
        else:
            hints.append('faixa_preco:acima_300')
    if discount_pct is not None:
        if discount_pct >= Decimal('70'):
            hints.append('desconto:desconto_70')
        if discount_pct >= Decimal('50'):
            hints.append('desconto:desconto_50')
        if discount_pct >= Decimal('30'):
            hints.append('desconto:desconto_30')
    return list(dict.fromkeys(hints))


def _marketplace(urls: list[str]) -> str:
    for url in urls:
        host = urlparse(url).netloc.lower()
        for marketplace, domains in MARKETPLACE_DOMAINS.items():
            if any(domain in host for domain in domains):
                return marketplace
    return ''


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text).lower()
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


# ---------------------------------------------------------------------------
# P0-2: Price mechanics helpers
# ---------------------------------------------------------------------------

def _classify_coupon(text: str, coupon_code: str) -> str:
    """Classify coupon type: percentual, valor_fixo, frete_gratis, or empty."""
    if not coupon_code:
        return ''
    if COUPON_FRETE_RE.search(text):
        return 'frete_gratis'
    # Check if the coupon code itself indicates a percentage
    # e.g. "CUPOM10" → 10%, "MELI20" → 20%
    digit_match = re.search(r'(\d{1,3})$', coupon_code)
    if digit_match:
        return 'percentual'
    if COUPON_PCT_RE.search(text):
        return 'percentual'
    if COUPON_VALUE_RE.search(text):
        return 'valor_fixo'
    return 'valor_fixo'  # default to valor_fixo for unknowns


def _extract_cashback_value(text: str) -> Decimal | None:
    match = CASHBACK_VALUE_RE.search(text)
    if match:
        return _parse_price(match.group(1))
    match_pct = CASHBACK_PCT_RE.search(text)
    if match_pct:
        try:
            return Decimal(match_pct.group(1))
        except (InvalidOperation, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# P0-3: Copy and format helpers
# ---------------------------------------------------------------------------

def _emoji_density(text: str) -> Decimal | None:
    if not text:
        return None
    emojis = EMOJI_CHAR_RE.findall(text)
    # Count words (split by whitespace)
    word_count = len(text.split())
    if word_count == 0:
        return Decimal('0') if emojis else None
    density = Decimal(len(emojis)) / Decimal(word_count)
    return density.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _top_emojis(text: str, limit: int = 5) -> list[str]:
    emojis = EMOJI_CHAR_RE.findall(text)
    if not emojis:
        return []
    from collections import Counter
    counts = Counter(emojis)
    return [emoji for emoji, _ in counts.most_common(limit)]


def _detect_headline(text: str) -> bool | None:
    if not text:
        return None
    first_line = text.split('\n')[0].strip()
    if not first_line:
        return None
    # Headline if first line has emoji prefix, is all caps, or starts with *
    if EMOJI_CHAR_RE.search(first_line[:3]):
        return True
    if first_line.startswith('*') or first_line.startswith('🔥') or first_line.startswith('🚨'):
        return True
    alpha_chars = [c for c in first_line if c.isalpha()]
    if alpha_chars and sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.7:
        return True
    return False


def _detect_cta(normalized: str) -> tuple[bool | None, list[str]]:
    if not normalized:
        return None, []
    found: list[str] = []
    for key, patterns in CTA_TERMS.items():
        if isinstance(patterns, str):
            if patterns in normalized:
                found.append(key)
        elif isinstance(patterns, (tuple, list)):
            if any(p in normalized for p in patterns):
                found.append(key)
    return bool(found) if found else False, found


def _classify_media(has_image: bool, text: str) -> str:
    # Simple heuristic: image from raw_type is classified upstream
    # This function adds granularity
    lower = text.lower()
    if has_image:
        # Heuristic: banner_proprio vs foto_oficial
        # Banner often has watermarks/brand text; we can't distinguish from text alone
        # Default to foto_oficial; banner_proprio would need image analysis
        if 'banner' in lower or 'propaganda' in lower or 'publicidade' in lower:
            return 'banner_proprio'
        return 'foto_oficial'
    if 'video' in lower or 'assista' in lower or 'youtube.com' in lower or 'youtu.be' in lower:
        return 'video'
    return 'texto'


def _detect_uppercase(text: str) -> bool | None:
    if not text:
        return None
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return None
    upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
    return upper_ratio > UPPERCASE_RATIO


# ---------------------------------------------------------------------------
# P1-5: Marketplace richer
# ---------------------------------------------------------------------------

def _marketplace_with_domain(urls: list[str]) -> tuple[str, str]:
    """Return (marketplace, unknown_domain). unknown_domain is '' when classified."""
    for url in urls:
        host = urlparse(url).netloc.lower()
        for marketplace, domains in MARKETPLACE_DOMAINS.items():
            if any(domain in host for domain in domains):
                return marketplace, ''
        # If URL exists but no known marketplace matched, record the domain
        if host:
            # Try to extract the main domain (e.g., 'www.example.com' → 'example.com')
            parts = host.split('.')
            if len(parts) >= 2:
                domain = '.'.join(parts[-2:]) if parts[-1] not in ('com', 'co', 'io') else '.'.join(parts[-3:]) if len(parts) >= 3 else host
            else:
                domain = host
            return 'desconhecido', domain
    return '', ''


def _detect_delivery_program(normalized: str) -> str:
    for program, terms in DELIVERY_PROGRAM_TERMS.items():
        if any(term in normalized for term in terms):
            return program
    return ''


# ---------------------------------------------------------------------------
# P1-6: Brand extraction
# ---------------------------------------------------------------------------

def _extract_brand(normalized: str) -> str:
    for brand in BRAND_PATTERNS:
        if brand in normalized:
            return brand
    return ''