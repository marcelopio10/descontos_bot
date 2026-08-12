"""
Scraper Shopee via Affiliate Open API (GraphQL).

Implementa a interface `scrape_categories` para busca por categoria usando
`productCatId` do `category_targets.py`. A API `productOfferV2` é chamada
por categoria e página, sem keyword, para cobrir melhor o catálogo disponível.

Mantém compatibilidade com o `ScraperAdapter` (`blocked`, `error_message`,
`pages_scraped`) e com o pipeline de ingestão existente.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient
from apps.marketplaces.services.shopee_collectors import ProductOfferCollector
from apps.marketplaces.services.search_provenance import sanitize_search_provenance

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 10  # ofertas por página/categoria (mantém ciclo rápido)
DEFAULT_CATEGORY_PAGES = 2  # evita repetir sempre o topo estável da Shopee
DEFAULT_LIST_TYPE = 0
DEFAULT_SORT_TYPE = 2  # maior comissão; sem keyword para cobrir a categoria inteira
MAX_SAFE_PRICE_RANGE_RATIO = Decimal('3')


class ShopeeScraper:
    """Scraper que consulta a Shopee Affiliate API por `productCatId`."""

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

            for page in range(1, DEFAULT_CATEGORY_PAGES + 1):
                try:
                    nodes = self._collector.fetch(
                        product_cat_id=category_id,
                        limit=DEFAULT_LIMIT,
                        page=page,
                        sort_type=DEFAULT_SORT_TYPE,
                        list_type=DEFAULT_LIST_TYPE,
                    )
                except Exception as exc:
                    log.error(
                        'Shopee erro em categoria=%s productCatId=%s page=%s: %s',
                        category_code,
                        category_id,
                        page,
                        exc,
                    )
                    continue

                self.pages_scraped += 1
                if not nodes:
                    break

                for item in nodes:
                    if _has_unsafe_price_range(item):
                        log.info(
                            'Shopee item rejeitado: faixa de preço insegura itemId=%s '
                            'shopId=%s priceMin=%s priceMax=%s',
                            item.get('itemId'),
                            item.get('shopId'),
                            item.get('priceMin'),
                            item.get('priceMax'),
                        )
                        continue

                    item = _with_price_variation_flag(item)

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
                if _has_unsafe_price_range(item):
                    log.info(
                        'Shopee item rejeitado: faixa de preço insegura itemId=%s '
                        'shopId=%s priceMin=%s priceMax=%s',
                        item.get('itemId'),
                        item.get('shopId'),
                        item.get('priceMin'),
                        item.get('priceMax'),
                    )
                    continue

                item = _with_price_variation_flag(item)

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

    def scrape_search_queries(self, queries) -> list[dict[str, Any]]:
        offers = []
        for query in queries:
            try:
                nodes = self._collector.fetch(keyword=query.query_text, limit=DEFAULT_LIMIT, page=1)
            except Exception as exc:
                log.error('Shopee busca direcionada falhou query=%s: %s', query.query_text, exc)
                continue
            self.pages_scraped += 1
            provenance = sanitize_search_provenance({'source_kind': query.source_kind, 'query_text': query.query_text, 'brand': query.brand, 'category_code': query.category_code, 'price_band': query.price_band, 'marketplace': query.marketplace})
            for item in nodes:
                if _has_unsafe_price_range(item):
                    continue
                item = _with_price_variation_flag(item)
                item_id, shop_id = str(item.get('itemId', '')), str(item.get('shopId', ''))
                product_url = item.get('productLink') or item.get('offerLink') or ''
                offers.append({'marketplace_code': 'shopee', 'title': item.get('productName', ''), 'current_price': item.get('priceMin') or item.get('price') or 0, 'price': item.get('priceMin') or item.get('price') or 0, 'original_price': _derive_original_price(item), 'discount_pct': item.get('priceDiscountRate') or 0, 'product_url': product_url, 'url': product_url, 'affiliate_url': item.get('offerLink') or '', 'image_url': item.get('imageUrl') or '', 'external_id': f'{item_id}:{shop_id}', 'raw_payload': item, 'search_provenance': provenance})
        return offers

def _derive_original_price(item: dict[str, Any]) -> float | None:
    """Calcula preço original a partir do desconto, quando confiável."""
    price = item.get('priceMin') or item.get('price') or 0
    rate = item.get('priceDiscountRate') or 0
    if 0 < float(rate) < 100 and float(price) > 0:
        return round(float(price) / (1 - float(rate) / 100), 2)
    return None


def _has_price_range(item: dict[str, Any]) -> bool:
    price_min = _to_decimal(item.get('priceMin') or item.get('price'))
    price_max = _to_decimal(item.get('priceMax'))
    return price_min is not None and price_max is not None and price_min != price_max


def _has_unsafe_price_range(item: dict[str, Any]) -> bool:
    """Rejeita só faixas de preço que ainda são inseguras para publicação.

    Shopee usa `priceMin != priceMax` para variações legítimas (cor/tamanho/kit).
    Publicamos `priceMin` como preço base e marcamos a variação, mas bloqueamos
    ranges absurdos ou payloads sem título/imagem/link, que podem induzir clique
    para uma variação diferente da exibida.
    """
    price_min = _to_decimal(item.get('priceMin') or item.get('price'))
    price_max = _to_decimal(item.get('priceMax'))
    if price_min is None or price_max is None or price_min == price_max:
        return False
    if price_min <= 0 or price_max <= 0:
        return True
    if price_max / price_min > MAX_SAFE_PRICE_RANGE_RATIO:
        return True
    if not str(item.get('productName') or '').strip():
        return True
    if not str(item.get('imageUrl') or '').strip():
        return True
    if not str(item.get('productLink') or item.get('offerLink') or '').strip():
        return True
    return False


def _with_price_variation_flag(item: dict[str, Any]) -> dict[str, Any]:
    if not _has_price_range(item):
        return item
    flagged = dict(item)
    flagged['has_price_variation'] = True
    flagged['published_price_source'] = 'priceMin'
    return flagged


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
