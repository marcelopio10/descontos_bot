"""
Scraper Shopee via Affiliate Open API (GraphQL).

Implementa a interface `scrape_categories` para busca por categoria usando
keywords mapeadas no `category_targets.py`. A API `productOfferV2` aceita
apenas keyword (não categoryId), então cada categoria contribui com palavras-chave
específicas que simulam a segmentação.

Mantém compatibilidade com o `ScraperAdapter` (`blocked`, `error_message`,
`pages_scraped`) e com o pipeline de ingestão existente.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient
from apps.marketplaces.services.shopee_collectors import ProductOfferCollector

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 10  # ofertas por categoria (mantém ciclo rápido)
DEFAULT_LIST_TYPE = 0
DEFAULT_SORT_TYPE = 2  # maior comissão; sem keyword para cobrir a categoria inteira


class ShopeeScraper:
    """Scraper que consulta a Shopee Affiliate API por categoria (keyword)."""

    def __init__(self, client: ShopeeAffiliateClient | None = None) -> None:
        self._client = client or ShopeeAffiliateClient()
        self._collector = ProductOfferCollector(self._client)
        self.blocked = False
        self.error_message = ''
        self.pages_scraped = 0

    # ------------------------------------------------------------------
    # Interface exigida pelo ScraperAdapter
    # ------------------------------------------------------------------

    def scrape_categories(
        self,
        targets: list[tuple[str, str, int | str, bool]],
    ) -> list[dict[str, Any]]:
        """Percorre IDs de categoria e coleta ofertas via API.

        targets: lista de (category_code, label, product_cat_id, trust_hint).
            - product_cat_id → passado direto para `productOfferV2(productCatId)`.
            - trust_hint → se True, injeta `category_hint` no payload.
        """
        offers: list[dict[str, Any]] = []
        seen: set[str] = set()

        for category_code, label, product_cat_id, trust_hint in targets:
            if self.blocked:
                break
            try:
                category_id = int(product_cat_id)
            except (TypeError, ValueError):
                log.warning(
                    'Shopee categoria [%s] ignorada: productCatId inválido=%r',
                    label,
                    product_cat_id,
                )
                continue

            log.info(
                'Shopee categoria [%s] productCatId=%s',
                label,
                category_id,
            )

            try:
                nodes = self._collector.fetch(
                    product_cat_id=category_id,
                    limit=DEFAULT_LIMIT,
                    sort_type=DEFAULT_SORT_TYPE,
                    list_type=DEFAULT_LIST_TYPE,
                )
            except Exception as exc:
                log.error(
                    'Shopee erro em categoria=%s productCatId=%s: %s',
                    category_code,
                    category_id,
                    exc,
                )
                continue

            self.pages_scraped += 1

            for item in nodes:
                if _has_price_range(item):
                    log.info(
                        'Shopee item rejeitado: faixa de preço inconsistente itemId=%s '
                        'shopId=%s priceMin=%s priceMax=%s',
                        item.get('itemId'),
                        item.get('shopId'),
                        item.get('priceMin'),
                        item.get('priceMax'),
                    )
                    continue

                item_id = str(item.get('itemId', ''))
                shop_id = str(item.get('shopId', ''))
                dedup_key = f'{item_id}:{shop_id}'
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                current_price = item.get('priceMin') or item.get('price') or 0
                product_url = item.get('productLink') or item.get('offerLink') or ''
                payload: dict[str, Any] = {
                    'marketplace_code': 'shopee',
                    'title': item.get('productName', ''),
                    'current_price': current_price,
                    'price': current_price,
                    'original_price': _derive_original_price(item),
                    'discount_pct': item.get('priceDiscountRate') or 0,
                    'product_url': product_url,
                    'url': product_url,
                    'affiliate_url': item.get('offerLink') or '',
                    'image_url': item.get('imageUrl') or '',
                    'external_id': dedup_key,
                    'raw_payload': item,
                    'shop_name': item.get('shopName') or '',
                    'sales': item.get('sales') or item.get('soldCount') or 0,
                    'rating': item.get('ratingStar') or 0,
                    'commission_rate': item.get('commissionRate') or 0,
                    'commission': item.get('commission') or 0,
                }

                if trust_hint:
                    payload['category_hint'] = category_code

                offers.append(payload)

        log.info(
            'Shopee category scraping concluído: ofertas=%d categorias=%d',
            len(offers), len(targets),
        )
        return offers

    def scrape_daily_deals(self, max_pages: int = 5) -> list[dict[str, Any]]:
        """Fallback genérico: busca sem keyword (destaques do dia)."""
        offers: list[dict[str, Any]] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            if self.blocked:
                break
            try:
                nodes = self._collector.fetch(keyword=None, limit=DEFAULT_LIMIT, page=page)
            except Exception as exc:
                log.error('Shopee daily deals page=%d erro: %s', page, exc)
                continue

            self.pages_scraped += 1
            if not nodes:
                break

            for item in nodes:
                if _has_price_range(item):
                    log.info(
                        'Shopee item rejeitado: faixa de preço inconsistente itemId=%s '
                        'shopId=%s priceMin=%s priceMax=%s',
                        item.get('itemId'),
                        item.get('shopId'),
                        item.get('priceMin'),
                        item.get('priceMax'),
                    )
                    continue

                item_id = str(item.get('itemId', ''))
                shop_id = str(item.get('shopId', ''))
                dedup_key = f'{item_id}:{shop_id}'
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                offers.append({
                    'marketplace_code': 'shopee',
                    'title': item.get('productName', ''),
                    'price': item.get('price') or item.get('priceMin') or 0,
                    'original_price': _derive_original_price(item),
                    'discount_pct': item.get('priceDiscountRate') or 0,
                    'url': item.get('productLink') or item.get('offerLink') or '',
                    'affiliate_url': item.get('offerLink') or '',
                    'image_url': item.get('imageUrl') or '',
                    'external_id': dedup_key,
                    'raw_payload': item,
                    'shop_name': item.get('shopName') or '',
                    'sales': item.get('sales') or 0,
                    'rating': item.get('ratingStar') or 0,
                    'commission_rate': item.get('commissionRate') or 0,
                    'commission': item.get('commission') or 0,
                })

        return offers


def _derive_original_price(item: dict[str, Any]) -> float | None:
    """Calcula preço original a partir do desconto, quando confiável."""
    price = item.get('priceMin') or item.get('price') or 0
    rate = item.get('priceDiscountRate') or 0
    if 0 < float(rate) < 100 and float(price) > 0:
        return round(float(price) / (1 - float(rate) / 100), 2)
    return None


def _has_price_range(item: dict[str, Any]) -> bool:
    """Rejeita produto Shopee com variações de preço sem SKU/imagem consistente."""
    price_min = _to_decimal(item.get('priceMin') or item.get('price'))
    price_max = _to_decimal(item.get('priceMax'))
    return price_min is not None and price_max is not None and price_min != price_max


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def build_from_env() -> ShopeeScraper:
    """Factory compatível com `adapters.build_adapter`."""
    return ShopeeScraper()
