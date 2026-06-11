import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from apps.marketplaces.models import Marketplace


ASIN_RE = re.compile(r'/(?:dp|gp/product|exec/obidos/ASIN)/([A-Z0-9]{10})')
PLAIN_ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')


@dataclass(frozen=True)
class NormalizedOffer:
    marketplace: Marketplace
    external_id: str
    title: str
    normalized_title: str
    offer_hash: str
    current_price: Decimal
    original_price: Decimal | None
    discount_pct: Decimal | None
    product_url: str
    affiliate_url: str
    asin: str
    price_collected_at: datetime | None
    image_url: str
    raw_payload: dict[str, Any]
    review_rating: Decimal | None = None
    review_count: int | None = None


class OfferNormalizationError(ValueError):
    pass


def normalize_offer(marketplace: Marketplace, payload: dict[str, Any]) -> NormalizedOffer:
    title = _clean_text(payload.get('nome') or payload.get('title') or '')
    product_url = _clean_url(payload.get('link_direto') or payload.get('product_url') or '')
    external_id = _clean_text(payload.get('id') or payload.get('external_id') or '')
    asin = _extract_payload_asin(payload, product_url, external_id)
    current_price = _to_money(payload.get('preco') or payload.get('current_price'))
    original_price = _to_optional_money(payload.get('preco_original') or payload.get('original_price'))
    discount_pct = _to_optional_pct(payload.get('desconto_pct') or payload.get('discount_pct'))

    if not title:
        raise OfferNormalizationError('Oferta sem título.')
    if not product_url:
        raise OfferNormalizationError('Oferta sem URL do produto.')
    if current_price <= Decimal('0.00'):
        raise OfferNormalizationError('Oferta sem preço atual válido.')
    if marketplace.code == 'amazon':
        if not asin:
            raise OfferNormalizationError('Oferta Amazon rejeitada: ASIN não encontrado.')
        external_id = asin
        product_url = f'https://www.amazon.com.br/dp/{asin}'

    if original_price is not None and original_price <= current_price:
        original_price = current_price

    if discount_pct is None and original_price and original_price > current_price:
        discount_pct = ((original_price - current_price) / original_price * Decimal('100')).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    normalized_title = normalize_title(title)
    stable_external_id = external_id or _fallback_external_id(product_url, normalized_title)

    return NormalizedOffer(
        marketplace=marketplace,
        external_id=stable_external_id,
        title=title,
        normalized_title=normalized_title,
        offer_hash=build_offer_hash(marketplace.code, stable_external_id, product_url),
        current_price=current_price,
        original_price=original_price,
        discount_pct=discount_pct or Decimal('0.00'),
        product_url=product_url,
        affiliate_url=_clean_url(payload.get('link_afiliado') or payload.get('affiliate_url') or ''),
        asin=asin,
        price_collected_at=None,
        image_url=_clean_url(payload.get('imagem') or payload.get('image_url') or ''),
        raw_payload=payload,
        review_rating=_to_optional_rating(
            payload.get('review_rating') or payload.get('rating') or payload.get('nota'),
        ),
        review_count=_to_optional_count(
            payload.get('review_count') or payload.get('reviews') or payload.get('total_avaliacoes'),
        ),
    )


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value)
    ascii_title = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', ascii_title.lower()).strip()


def build_offer_hash(marketplace_code: str, external_id: str, product_url: str) -> str:
    source = '|'.join([marketplace_code.strip().lower(), external_id.strip().lower(), product_url.strip()])
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def extract_asin(value: Any) -> str:
    return _extract_asin(_clean_text(value))


def _clean_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _extract_asin(product_url: str) -> str:
    value = (product_url or '').strip()
    if PLAIN_ASIN_RE.match(value):
        return value

    parts = urlsplit(value)
    match = ASIN_RE.search(parts.path)
    return match.group(1) if match else ''


def _extract_payload_asin(payload: dict[str, Any], product_url: str, external_id: str) -> str:
    candidates = [
        payload.get('asin'),
        product_url,
        payload.get('link_afiliado'),
        payload.get('affiliate_url'),
        external_id,
    ]
    for candidate in candidates:
        asin = _extract_asin(_clean_text(candidate))
        if asin:
            return asin
    return ''


def _clean_url(value: Any) -> str:
    url = _clean_text(value)
    if not url:
        return ''
    parts = urlsplit(url)
    if not parts.scheme:
        return ''
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))


def _to_money(value: Any) -> Decimal:
    money = _to_decimal(value)
    if money is None:
        raise OfferNormalizationError('Valor monetário inválido.')
    return money.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _to_optional_money(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    return _to_money(value)


def _to_optional_pct(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    pct = _to_decimal(value)
    if pct is None:
        return None
    return pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _to_optional_rating(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    rating = _to_decimal(value)
    if rating is None:
        return None
    if rating < 0 or rating > Decimal('5'):
        return None
    return rating.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _to_optional_count(value: Any) -> int | None:
    if value in (None, ''):
        return None
    text = str(value).strip()
    text = re.sub(r'[^\d]', '', text)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace('R$', '').replace('%', '').replace(' ', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _fallback_external_id(product_url: str, normalized_title: str) -> str:
    source = f'{product_url}|{normalized_title}'
    return hashlib.sha1(source.encode('utf-8')).hexdigest()
