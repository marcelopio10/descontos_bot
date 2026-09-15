from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import (
    NormalizedOffer,
    OfferNormalizationError,
    get_mercadolivre_path_item_id,
    normalize_offer,
)

from .mercadolivre_price_resolver import PriceSnapshot

_ALLOWED_HOSTS = frozenset({
    'mercadolivre.com.br',
    'www.mercadolivre.com.br',
    'produto.mercadolivre.com.br',
})
_ITEM_ID_RE = re.compile(r'^MLB[0-9]+$')


class MercadoLivreProductNormalizer:
    def normalize(
        self,
        item: dict[str, Any],
        *,
        marketplace: Marketplace,
        price: PriceSnapshot,
        seller: dict[str, Any] | None,
        observed_at: datetime,
    ) -> NormalizedOffer:
        item_id = str(item.get('id') or '').strip().upper()
        if not _ITEM_ID_RE.fullmatch(item_id):
            raise OfferNormalizationError('Item Mercado Livre sem ID MLB válido.')

        product_url = self._canonical_product_url(item_id, item.get('permalink'))
        seller_data: dict[str, Any] = seller or {}
        raw_item_seller = item.get('seller')
        item_seller: dict[str, Any] = raw_item_seller if isinstance(raw_item_seller, dict) else {}
        seller_id = str(seller_data.get('id') or item_seller.get('id') or '').strip()
        seller_name = str(seller_data.get('nickname') or item_seller.get('nickname') or '').strip()
        image_url = self._image_url(item)
        payload = {
            'id': item_id,
            'nome': item.get('title') or '',
            'preco': str(price.current_price),
            'preco_original': str(price.original_price) if price.original_price is not None else '',
            'desconto_pct': str(price.discount_pct),
            'link_direto': product_url,
            'link_afiliado': '',
            'imagem': image_url,
            'seller_id': seller_id,
            'seller_name': seller_name,
            'currency_code': price.currency_code,
            'listing_status': item.get('status') or '',
            'condition': item.get('condition') or '',
            'available_quantity': item.get('available_quantity'),
            'collection_source': 'mercadolivre_api',
            'search_provenance': item.get('_search_provenance') or {},
            'category_hint': item.get('_category_hint') or '',
            'price_source': price.source,
            'price_reference_date': price.reference_date,
            'contextual_price_error': price.error_code,
            'api_item': self._safe_item_payload(item),
            'seller_reputation': self._safe_seller_reputation(seller_data),
        }
        normalized = normalize_offer(marketplace, payload)
        return replace(
            normalized,
            price_collected_at=observed_at,
            seller_id=seller_id,
            seller_name=seller_name,
            currency_code=price.currency_code,
            listing_status=str(item.get('status') or '').strip(),
            condition=str(item.get('condition') or '').strip(),
            available_quantity=self._quantity(item.get('available_quantity')),
            collection_source='mercadolivre_api',
        )

    @staticmethod
    def _canonical_product_url(item_id: str, permalink: Any) -> str:
        if permalink is None or permalink == '':
            return f'https://www.mercadolivre.com.br/p/{item_id}'
        if not isinstance(permalink, str):
            raise OfferNormalizationError('Permalink Mercado Livre deve ser texto.')
        if any(ord(char) < 32 or ord(char) == 127 for char in permalink):
            raise OfferNormalizationError('Permalink Mercado Livre inválido ou externo.')
        value = permalink.strip()
        if not value:
            raise OfferNormalizationError('Permalink Mercado Livre inválido ou externo.')

        parts = None
        port = None
        try:
            parsed_parts = urlsplit(value)
            port = parsed_parts.port
            parts = parsed_parts
        except (TypeError, ValueError):
            pass
        if parts is None:
            raise OfferNormalizationError(
                'Permalink Mercado Livre inválido ou externo.',
            )
        hostname = (parts.hostname or '').lower()
        decoded_path = parts.path
        for _ in range(5):
            unquoted_path = unquote(decoded_path)
            if unquoted_path == decoded_path:
                break
            decoded_path = unquoted_path
        else:
            decoded_path = ''
        path_item_id = get_mercadolivre_path_item_id(decoded_path)
        if (
            not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and parts.scheme == 'https'
            and hostname in _ALLOWED_HOSTS
            and port is None
            and parts.username is None
            and parts.password is None
            and parts.path
            and decoded_path == parts.path
            and not any(ord(char) < 32 or ord(char) == 127 for char in decoded_path)
            and '\\' not in decoded_path
            and not any(segment in {'.', '..'} for segment in decoded_path.split('/'))
            and path_item_id == item_id
        ):
            return urlunsplit((parts.scheme, hostname, parts.path, '', ''))
        raise OfferNormalizationError('Permalink Mercado Livre inválido ou externo.')


    @staticmethod
    def _image_url(item: dict[str, Any]) -> str:
        pictures = item.get('pictures') or []
        if pictures and isinstance(pictures[0], dict):
            value = pictures[0].get('secure_url') or pictures[0].get('url') or ''
            if str(value).startswith('https://'):
                return str(value)
        thumbnail = str(item.get('thumbnail') or '')
        return thumbnail if thumbnail.startswith('https://') else ''

    @staticmethod
    def _safe_item_payload(item: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            'id',
            'title',
            'permalink',
            'status',
            'condition',
            'category_id',
            'price',
            'base_price',
            'original_price',
            'currency_id',
            'available_quantity',
            'listing_type_id',
        )
        safe = {key: item[key] for key in allowed if key in item}
        seller = item.get('seller')
        if isinstance(seller, dict):
            safe['seller'] = {
                key: seller[key]
                for key in ('id', 'nickname')
                if key in seller
            }
        pictures = item.get('pictures')
        if isinstance(pictures, list):
            safe['pictures'] = [
                {
                    key: picture[key]
                    for key in ('id', 'url', 'secure_url')
                    if key in picture
                }
                for picture in pictures[:1]
                if isinstance(picture, dict)
            ]
        return safe

    @staticmethod
    def _safe_seller_reputation(seller: dict[str, Any]) -> dict[str, Any]:
        reputation = seller.get('seller_reputation')
        if not isinstance(reputation, dict):
            return {}
        return {
            key: reputation[key]
            for key in ('level_id', 'power_seller_status', 'transactions')
            if key in reputation
        }

    @staticmethod
    def _quantity(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OfferNormalizationError('Quantidade disponível inválida.')
        return value
