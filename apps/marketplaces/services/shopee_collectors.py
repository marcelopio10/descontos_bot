"""Coletores de ofertas da Shopee Affiliate API.

`ProductOfferCollector` busca produtos elegíveis via `productOfferV2`. O schema
exato é confirmado contra a conta real na primeira execução com credenciais
(Sprint 7B.3); o parsing é defensivo para tolerar campos ausentes.
"""

import logging

from django.conf import settings

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient

log = logging.getLogger('apps.marketplaces.shopee')

PRODUCT_OFFER_QUERY = """
query productOfferV2(
  $keyword: String,
  $limit: Int,
  $page: Int,
  $productCatId: Int,
  $sortType: Int,
  $listType: Int
) {
  productOfferV2(
    keyword: $keyword,
    limit: $limit,
    page: $page,
    productCatId: $productCatId,
    sortType: $sortType,
    listType: $listType
  ) {
    nodes {
      itemId
      shopId
      productName
      price
      priceMin
      priceMax
      priceDiscountRate
      imageUrl
      productLink
      offerLink
      commissionRate
      commission
      sales
      ratingStar
      shopName
      shopType
      productCatIds
      periodStartTime
      periodEndTime
    }
    pageInfo {
      page
      limit
      hasNextPage
      scrollId
    }
  }
}
""".strip()


class ProductOfferCollector:
    def __init__(self, client: ShopeeAffiliateClient | None = None):
        self.client = client or ShopeeAffiliateClient()

    def fetch(
        self,
        keyword: str | None = None,
        limit: int | None = None,
        page: int = 1,
        product_cat_id: int | None = None,
        sort_type: int | None = None,
        list_type: int | None = None,
    ) -> list[dict]:
        resolved_limit = limit or settings.SHOPEE_AFFILIATE_DEFAULT_LIMIT
        variables: dict = {'limit': resolved_limit, 'page': page}
        if keyword:
            variables['keyword'] = keyword
        if product_cat_id is not None:
            variables['productCatId'] = product_cat_id
        if sort_type is not None:
            variables['sortType'] = sort_type
        if list_type is not None:
            variables['listType'] = list_type

        data = self.client.execute(PRODUCT_OFFER_QUERY, variables)
        block = data.get('productOfferV2') or {}
        nodes = block.get('nodes') or []

        if not nodes:
            log.warning(
                'shopee_product_offer_empty keyword=%r product_cat_id=%r page=%s limit=%s',
                keyword,
                product_cat_id,
                page,
                resolved_limit,
            )
        return nodes
