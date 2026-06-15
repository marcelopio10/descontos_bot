"""Normaliza um item da Shopee Affiliate API para o domínio `Offer`.

Reusa `apps.offers.services.normalizer.normalize_offer` (parsing monetário,
validação, título normalizado) e força a deduplicação por `itemId + shopId`,
independente da URL — conforme a regra de negócio da Shopee.
"""

import dataclasses
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import (
    NormalizedOffer,
    OfferNormalizationError,
    build_offer_hash,
    normalize_offer,
)

SHOPEE_CODE = 'shopee'


def shopee_external_id(item: dict) -> str:
    return f"{item.get('itemId')}:{item.get('shopId')}"


def _to_decimal(value) -> Decimal | None:
    if value in (None, ''):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _derive_original_price(current, discount_rate) -> Decimal | None:
    """Deriva o preço original a partir do preço atual e do desconto (%).

    Só deriva com desconto confiável (0 < rate < 100); senão retorna None para
    não inventar preço de tabela.
    """
    price = _to_decimal(current)
    rate = _to_decimal(discount_rate)
    if price is None or rate is None:
        return None
    if rate <= 0 or rate >= 100:
        return None
    original = price / (Decimal('1') - rate / Decimal('100'))
    return original.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def normalize_shopee_item(marketplace: Marketplace, item: dict) -> NormalizedOffer:
    if not item.get('itemId') or not item.get('shopId'):
        raise OfferNormalizationError('Item Shopee sem itemId/shopId.')

    external_id = shopee_external_id(item)
    current_price = item.get('priceMin') or item.get('price')
    discount_rate = item.get('priceDiscountRate')

    payload = {
        'title': item.get('productName'),
        'product_url': item.get('productLink'),
        'id': external_id,
        'current_price': current_price,
        'discount_pct': discount_rate,
        'affiliate_url': item.get('offerLink') or '',
        'image_url': item.get('imageUrl') or '',
        'rating': item.get('ratingStar'),
        # Item bruto preservado para auditoria/score futuro (comissão, vendas...).
        'shopee': item,
    }

    original_price = _derive_original_price(current_price, discount_rate)
    if original_price is not None:
        payload['original_price'] = str(original_price)

    normalized = normalize_offer(marketplace, payload)

    # Deduplicação estrita por itemId+shopId, independente da URL da campanha.
    return dataclasses.replace(
        normalized,
        offer_hash=build_offer_hash(SHOPEE_CODE, external_id, ''),
    )
