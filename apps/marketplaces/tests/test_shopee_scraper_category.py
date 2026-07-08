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


class PagedFakeCollector:
    def __init__(self):
        self.calls = []

    def fetch(self, **kwargs):
        self.calls.append(kwargs)
        page = kwargs.get('page')
        return [
            {
                'itemId': 123 if page == 1 else 789,
                'shopId': 456,
                'productName': f'Oferta página {page}',
                'priceMin': '48.99',
                'priceDiscountRate': 30,
                'productLink': f'https://shopee.com.br/product/456/{123 if page == 1 else 789}',
                'offerLink': 'https://s.shopee.com.br/abc',
                'imageUrl': 'https://cf.shopee.com.br/img.jpg',
                'productCatIds': [100636, 100717, 101219],
            },
        ]


class ShopeeScraperCategoryTests(SimpleTestCase):
    def test_scrape_categories_fetches_multiple_pages_per_category(self):
        scraper = ShopeeScraper(client=None)
        fake = PagedFakeCollector()
        scraper._collector = fake

        offers = scraper.scrape_categories([
            ('casa_cozinha', 'Casa e Cozinha', 100636, True),
        ])

        self.assertEqual(
            fake.calls,
            [
                {'product_cat_id': 100636, 'limit': 10, 'page': 1, 'sort_type': 2, 'list_type': 0},
                {'product_cat_id': 100636, 'limit': 10, 'page': 2, 'sort_type': 2, 'list_type': 0},
            ],
        )
        self.assertEqual([offer['external_id'] for offer in offers], ['123:456', '789:456'])
        self.assertEqual(scraper.pages_scraped, 2)

    def test_scrape_categories_uses_category_id_not_keyword_and_emits_normalizer_keys(self):
        scraper = ShopeeScraper(client=None)
        fake = FakeCollector()
        scraper._collector = fake

        offers = scraper.scrape_categories([
            ('casa_cozinha', 'Casa e Cozinha', 100636, True),
        ])

        self.assertEqual(
            fake.calls,
            [
                {'product_cat_id': 100636, 'limit': 10, 'page': 1, 'sort_type': 2, 'list_type': 0},
                {'product_cat_id': 100636, 'limit': 10, 'page': 2, 'sort_type': 2, 'list_type': 0},
            ],
        )
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer['category_hint'], 'casa_cozinha')
        self.assertEqual(offer['current_price'], '48.99')
        self.assertEqual(offer['product_url'], 'https://shopee.com.br/product/456/123')
        self.assertEqual(offer['discount_pct'], 30)

    def test_scrape_categories_allows_safe_price_range_and_flags_variation(self):
        scraper = ShopeeScraper(client=None)
        fake = FakeCollector()
        fake.fetch = lambda **kwargs: [{
            'itemId': 123,
            'shopId': 456,
            'productName': 'Percarbonato 500g/1kg',
            'priceMin': '17.99',
            'priceMax': '49.99',
            'priceDiscountRate': 45,
            'productLink': 'https://shopee.com.br/product/456/123',
            'offerLink': 'https://s.shopee.com.br/abc',
            'imageUrl': 'https://cf.shopee.com.br/img-1kg.jpg',
        }]
        scraper._collector = fake

        offers = scraper.scrape_categories([
            ('casa_cozinha', 'Casa e Cozinha', 100636, True),
        ])

        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer['current_price'], '17.99')
        self.assertTrue(offer['raw_payload']['has_price_variation'])
        self.assertEqual(offer['raw_payload']['published_price_source'], 'priceMin')

    def test_scrape_categories_rejects_absurd_price_range(self):
        scraper = ShopeeScraper(client=None)
        fake = FakeCollector()
        fake.fetch = lambda **kwargs: [{
            'itemId': 123,
            'shopId': 456,
            'productName': 'Percarbonato 500g/1kg',
            'priceMin': '17.99',
            'priceMax': '79.99',
            'priceDiscountRate': 45,
            'productLink': 'https://shopee.com.br/product/456/123',
            'offerLink': 'https://s.shopee.com.br/abc',
            'imageUrl': 'https://cf.shopee.com.br/img-1kg.jpg',
        }]
        scraper._collector = fake

        offers = scraper.scrape_categories([
            ('casa_cozinha', 'Casa e Cozinha', 100636, True),
        ])

        self.assertEqual(offers, [])
