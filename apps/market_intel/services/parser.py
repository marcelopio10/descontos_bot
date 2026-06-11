import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

MARKETPLACE_DOMAINS = {
    'amazon': ('amazon.', 'amzn.to'),
    'mercadolivre': ('mercadolivre.', 'mercadolivre.com', 'meli.la'),
    'shopee': ('shopee.',),
    'magalu': ('magazineluiza.', 'magalu.'),
    'aliexpress': ('aliexpress.',),
}

CATEGORY_KEYWORDS = {
    'casa/cozinha': ('air fryer', 'panela', 'cafeteira', 'cozinha'),
    'moda': ('tenis', 'camiseta', 'calca', 'vestido'),
    'tecnologia': ('notebook', 'monitor', 'fone', 'carregador', 'ssd'),
    'beleza': ('perfume', 'creme', 'shampoo'),
}

URGENCY_TERMS = ('corre', 'acabando', 'relampago', 'só hoje', 'so hoje', 'ultimas unidades', 'últimas unidades')
PROOF_TERMS = ('muito vendido', 'bem avaliado', 'viral', 'campeao', 'campeão')

PRICE_RE = re.compile(r'R\$\s*([0-9\.]+,\d{2}|[0-9]+(?:[\.,]\d{2})?)', re.IGNORECASE)
COUPON_RE = re.compile(
    r'\b(?:(?:cupom)\s*[:=\-]?\s*|(?:use|aplique)\s+(?:o\s+)?(?:cupom\s+)?)([A-Z0-9][A-Z0-9_-]{2,20})\b',
    re.IGNORECASE,
)
URL_RE = re.compile(r'https?://[^\s)\]}>"]+', re.IGNORECASE)


def parse_observed_message(text: str, has_image: bool = False, urls: list[str] | None = None) -> dict:
    urls = urls or URL_RE.findall(text or '')
    normalized = _normalize_text(text or '')
    prices = [_parse_price(match) for match in PRICE_RE.findall(text or '')]
    prices = [price for price in prices if price is not None]
    original_price = prices[0] if len(prices) >= 2 else None
    price = prices[-1] if prices else None
    discount_pct = _discount_pct(original_price, price)
    coupon = _extract_coupon(text or '')
    labels = _labels(normalized, price, coupon, has_image)
    category = _category(normalized)
    hints = _scraper_hints(category, price, normalized)

    return {
        'marketplace': _marketplace(urls),
        'price': _decimal_to_str(price),
        'original_price': _decimal_to_str(original_price),
        'discount_pct': _decimal_to_str(discount_pct),
        'coupon': coupon,
        'labels': labels,
        'category': category,
        'scraper_hints': hints,
    }


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


def _labels(normalized: str, price: Decimal | None, coupon: str, has_image: bool) -> list[str]:
    labels: list[str] = []
    if any(term in normalized for term in URGENCY_TERMS):
        labels.append('urgencia')
    if any(term in normalized for term in PROOF_TERMS):
        labels.append('prova_social')
    if coupon:
        labels.append('cupom')
    if has_image:
        labels.append('imagem')
    if price is not None:
        if price <= Decimal('50'):
            labels.append('ate_50')
        elif price <= Decimal('100'):
            labels.append('ate_100')
        elif price <= Decimal('300'):
            labels.append('ate_300')
        else:
            labels.append('acima_300')
    return labels


def _category(normalized: str) -> str:
    for category, terms in CATEGORY_KEYWORDS.items():
        if any(term in normalized for term in terms):
            return category
    return ''


def _scraper_hints(category: str, price: Decimal | None, normalized: str) -> list[str]:
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
    return list(dict.fromkeys(hints))


def _marketplace(urls: list[str]) -> str:
    for url in urls:
        host = urlparse(url).netloc.lower()
        for marketplace, domains in MARKETPLACE_DOMAINS.items():
            if any(domain in host for domain in domains):
                return marketplace
    return ''


def _normalize_text(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize('NFKD', text).lower()
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
