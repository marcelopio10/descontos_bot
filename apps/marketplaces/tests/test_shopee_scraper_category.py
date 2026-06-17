from django.test import SimpleTestCase

from scrapers.shopee import ShopeeScraper


class FakeCollector:
    def __init__(self):
        self.calls = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                'itemId': 123,
                'shopId': 456,
                'productName': 'Bule de Vidro',
                'priceMin': '48.99',
                'priceDiscountRate': 30,
                'productLink': 'https://shopee.com.br/product/456/123',
                'offerLink': 'https://s.shopee.com.br/abc',
                'imageUrl': 'https://cf.shopee.com.br/img.jpg',
                'productCatIds': [100636, 100717, 101219],
            },
        ]


class ShopeeScraperCategoryTests(SimpleTestCase):
    def test_scrape_categories_uses_category_id_not_keyword_and_emits_normalizer_keys(self):
        scraper = ShopeeScraper(client=None)
        fake = FakeCollector()
        scraper._collector = fake

        offers = scraper.scrape_categories([
            ('casa_cozinha', 'Casa e Cozinha', 100636, True),
        ])

        self.assertEqual(fake.calls, [{'product_cat_id': 100636, 'limit': 10, 'sort_type': 2, 'list_type': 0}])
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer['category_hint'], 'casa_cozinha')
        self.assertEqual(offer['current_price'], '48.99')
        self.assertEqual(offer['product_url'], 'https://shopee.com.br/product/456/123')
        self.assertEqual(offer['discount_pct'], 30)
