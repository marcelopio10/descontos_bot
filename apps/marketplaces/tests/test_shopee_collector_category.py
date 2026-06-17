from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.shopee_collectors import ProductOfferCollector


class FakeClient:
    def __init__(self):
        self.calls = []

    def execute(self, query, variables):
        self.calls.append((query, variables))
        return {'productOfferV2': {'nodes': [], 'pageInfo': {'hasNextPage': False}}}


class ShopeeCollectorCategoryTests(SimpleTestCase):
    @override_settings(SHOPEE_AFFILIATE_DEFAULT_LIMIT=50)
    def test_fetch_uses_product_category_without_keyword(self):
        client = FakeClient()
        collector = ProductOfferCollector(client=client)

        collector.fetch(product_cat_id=100636, limit=25, page=2, sort_type=2, list_type=0)

        query, variables = client.calls[0]
        self.assertIn('$productCatId: Int', query)
        self.assertIn('productCatId: $productCatId', query)
        self.assertEqual(
            variables,
            {
                'limit': 25,
                'page': 2,
                'productCatId': 100636,
                'sortType': 2,
                'listType': 0,
            },
        )
        self.assertNotIn('keyword', variables)
