import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.search_provenance import build_sanitized_raw_payload


ASIN_RE = re.compile(r'/(?:dp|gp/product|exec/obidos/ASIN)/([A-Z0-9]{10})')
PLAIN_ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')
MAX_REVIEW_COUNT = 2_147_483_647
_MERCADOLIVRE_ALLOWED_HOSTS = frozenset({
    'mercadolivre.com.br',
    'www.mercadolivre.com.br',
    'produto.mercadolivre.com.br',
})
_MERCADOLIVRE_ITEM_ID_RE = re.compile(r'^MLB[0-9]+$')


@dataclass(frozen=True)
class NormalizedOffer:
    marketplace: Marketplace
    external_id: str
    title: str
    normalized_title: str
    offer_hash: str
    produto_canonico_id: str
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
    seller_id: str = ''
    seller_name: str = ''
    currency_code: str = ''
    listing_status: str = ''
    condition: str = ''
    available_quantity: int | None = None
    collection_source: str = ''


class OfferNormalizationError(ValueError):
    pass


def normalize_offer(marketplace: Marketplace, payload: dict[str, Any]) -> NormalizedOffer:
    title = _clean_text(payload.get('nome') or payload.get('title') or '')
    raw_product_url = payload.get('link_direto') or payload.get('product_url') or ''
    if marketplace.code == 'mercadolivre' and isinstance(raw_product_url, str):
        if (
            _contains_url_control(raw_product_url)
            or '?' in raw_product_url
            or '#' in raw_product_url
        ):
            raise OfferNormalizationError('Oferta Mercado Livre rejeitada: URL do produto inválida.')
    product_url = _clean_url(raw_product_url)
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
    if marketplace.code == 'mercadolivre':
        product_url = _clean_mercadolivre_product_url(product_url, external_id)
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
    seller_payload = payload.get('seller')
    seller_id_value = payload.get('seller_id')
    seller_name_value = payload.get('seller_name') or payload.get('vendedor')
    if isinstance(seller_payload, dict):
        seller_id_value = seller_id_value or seller_payload.get('id')
        seller_name_value = seller_name_value or seller_payload.get('nickname')

    return NormalizedOffer(
        marketplace=marketplace,
        external_id=stable_external_id,
        title=title,
        normalized_title=normalized_title,
        offer_hash=build_offer_hash(marketplace.code, stable_external_id, product_url),
        produto_canonico_id=build_produto_canonico_id(marketplace.code, asin, stable_external_id),
        current_price=current_price,
        original_price=original_price,
        discount_pct=discount_pct or Decimal('0.00'),
        product_url=product_url,
        affiliate_url=_clean_url(payload.get('link_afiliado') or payload.get('affiliate_url') or ''),
        asin=asin,
        price_collected_at=None,
        image_url=_clean_url(payload.get('imagem') or payload.get('image_url') or ''),
        raw_payload=build_sanitized_raw_payload(payload),
        review_rating=_to_optional_rating(
            payload.get('review_rating') or payload.get('rating') or payload.get('nota'),
        ),
        review_count=_to_optional_count(
            payload.get('review_count') or payload.get('reviews') or payload.get('total_avaliacoes'),
        ),
        seller_id=_clean_text(seller_id_value),
        seller_name=_clean_text(seller_name_value),
        currency_code=_clean_text(payload.get('currency_code') or payload.get('currency_id')).upper(),
        listing_status=_clean_text(payload.get('listing_status') or payload.get('status')),
        condition=_clean_text(payload.get('condition') or payload.get('condicao')),
        available_quantity=_available_quantity(payload),
        collection_source=_clean_text(payload.get('collection_source') or payload.get('source')),
    )


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value)
    ascii_title = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', ascii_title.lower()).strip()


def build_offer_hash(marketplace_code: str, external_id: str, product_url: str) -> str:
    source = '|'.join([marketplace_code.strip().lower(), external_id.strip().lower(), product_url.strip()])
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def build_produto_canonico_id(marketplace_code: str, asin: str, external_id: str) -> str:
    """Best-effort canonical product id, used only for internal curation dedup.

    Distinct from `offer_hash` (identity of one *listing*/URL): this tries to
    identify the underlying *physical product* so the curation batch optimizer
    can avoid publishing two near-identical listings (Sprint 5 / achado P8).

    - Amazon: o ASIN identifica o produto de forma exata, independente de
      vendedor/buy-box — é o caso "resolvido" (equivalente a um GTIN real).
    - Shopee: `external_id` chega como `"{itemId}:{shopId}"` (ver
      `shopee_normalizer.shopee_external_id`). Usamos só o `itemId`, pois o
      mesmo anúncio pode ser vendido por lojas (shopId) diferentes — dropar o
      shopId é o que de fato deduplica o produto entre vendedores.
    - Demais marketplaces (ex.: Mercado Livre): não há ASIN/GTIN no payload.
      Cai para `external_id` (o próprio identificador do anúncio). Isso é uma
      limitação conhecida e intencional: NÃO deduplica o mesmo produto
      anunciado por vendedores diferentes (cada um tem seu próprio ID de
      anúncio). Deliberadamente não implementamos heurística de marca+modelo
      via NLP aqui — o risco de fundir produtos diferentes por engano supera o
      ganho de um dedup best-effort mais agressivo. Mesmo espírito das
      limitações já documentadas em `shopee_normalizer.py`.
    """
    code = (marketplace_code or '').strip().lower()
    cleaned_external_id = (external_id or '').strip()

    if code == 'amazon' and asin:
        return f'amazon:{asin.strip()}'

    if code == 'shopee' and cleaned_external_id:
        item_id = cleaned_external_id.split(':', 1)[0].strip()
        if item_id:
            return f'shopee:{item_id}'

    if cleaned_external_id:
        return f'{code}:{cleaned_external_id}'

    return ''


def extract_asin(value: Any) -> str:
    return _extract_asin(_clean_text(value))


def _clean_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != '':
            return value
    return None


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


def _contains_url_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _clean_mercadolivre_product_url(value: str, external_id: str) -> str:
    if not _MERCADOLIVRE_ITEM_ID_RE.fullmatch(external_id):
        raise OfferNormalizationError('Oferta Mercado Livre rejeitada: ID MLB inválido.')

    parts = None
    port = None
    try:
        parsed_parts = urlsplit(value)
        port = parsed_parts.port
        parts = parsed_parts
    except (TypeError, ValueError):
        pass
    if parts is None:
        raise OfferNormalizationError('Oferta Mercado Livre rejeitada: URL do produto inválida.')

    decoded_path = parts.path
    for _ in range(5):
        unquoted_path = unquote(decoded_path)
        if unquoted_path == decoded_path:
            break
        decoded_path = unquoted_path
    else:
        decoded_path = ''
    path_item_id = get_mercadolivre_path_item_id(decoded_path)
    if not (
        not any(ord(char) < 32 or ord(char) == 127 for char in value)
        and not any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
        and parts.scheme == 'https'
        and parts.hostname is not None
        and parts.hostname.lower() in _MERCADOLIVRE_ALLOWED_HOSTS
        and port is None
        and parts.username is None
        and parts.password is None
        and bool(parts.path)
        and decoded_path == parts.path
        and '?' not in value
        and '#' not in value
        and not parts.fragment
        and '\\' not in decoded_path
        and not any(segment in {'.', '..'} for segment in decoded_path.split('/'))
        and path_item_id == external_id
    ):
        raise OfferNormalizationError('Oferta Mercado Livre rejeitada: URL do produto inválida.')
    return urlunsplit(('https', parts.hostname.lower(), parts.path, '', ''))


_MERCADOLIVRE_PRODUCT_SEGMENT_RE = re.compile(
    r'MLB-?([0-9]+)(?:-(?P<slug>[\w.-]+))?',
    re.IGNORECASE,
)
_MERCADOLIVRE_DERIVED_SEGMENT_RE = re.compile(
    r'MLB([0-9]+)',
    re.IGNORECASE,
)


def get_mercadolivre_path_item_id(path: str) -> str:
    segments = path.split('/')
    if len(segments) == 2:
        match = _MERCADOLIVRE_PRODUCT_SEGMENT_RE.fullmatch(segments[1])
        if match and not _is_safe_mercadolivre_slug(match.group('slug')):
            match = None
    elif len(segments) == 3 and segments[1] == 'p':
        match = _MERCADOLIVRE_DERIVED_SEGMENT_RE.fullmatch(segments[2])
    elif (
        len(segments) == 4
        and segments[2] == 'p'
        and re.fullmatch(r'[\w.-]+', segments[1])
        and _is_safe_mercadolivre_slug(segments[1])
    ):
        match = _MERCADOLIVRE_DERIVED_SEGMENT_RE.fullmatch(segments[3])
    else:
        match = None
    return f'MLB{match.group(1)}'.upper() if match else ''


def is_canonical_mercadolivre_product_path(path: str) -> bool:
    return bool(get_mercadolivre_path_item_id(path))


def _is_safe_mercadolivre_slug(slug: str | None) -> bool:
    if slug is None:
        return True
    return (
        slug not in {'.', '..'}
        and '..' not in slug
        and not re.search(r'MLB-?[0-9]+', slug, re.IGNORECASE)
    )


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
        count = int(text)
    except ValueError:
        return None
    if count > MAX_REVIEW_COUNT:
        return None
    return count


def _available_quantity(payload: dict[str, Any]) -> int | None:
    if 'available_quantity' in payload:
        return _to_optional_quantity(payload['available_quantity'])
    if 'quantidade_disponivel' in payload:
        return _to_optional_quantity(payload['quantidade_disponivel'])
    return None


def _to_optional_quantity(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OfferNormalizationError('Quantidade disponível inválida.')
    return value


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
