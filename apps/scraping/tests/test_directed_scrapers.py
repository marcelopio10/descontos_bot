from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.search_query_planner import SearchQuery
from scrapers.amazon import AmazonScraper
from scrapers.mercado_livre import MercadoLivreScraper
from scrapers.shopee import ShopeeScraper


class DirectedScraperQueryTests(SimpleTestCase):
    def setUp(self):
        self.query = SearchQuery('amazon', 'nike tênis', 'radar_brand', brand='nike')

    @patch.object(AmazonScraper, '_scrape_urls', return_value=[])
    def test_amazon_converts_query_to_search_url_and_provenance(self, scrape):
        AmazonScraper().scrape_search_queries((self.query,))
        items = scrape.call_args.args[0]
        self.assertIn('nike+t%C3%AAnis', items[0][1])
        self.assertEqual(items[0][4]['source_kind'], 'radar_brand')

    @patch.object(MercadoLivreScraper, '_scrape_search_urls', return_value=[])
    def test_mercado_livre_converts_query_to_search_url(self, scrape):
        query = SearchQuery('mercadolivre', 'growth whey', 'priority_catalog', brand='growth')
        MercadoLivreScraper().scrape_search_queries((query,))
        items = scrape.call_args.args[0]
        self.assertIn('growth%20whey', items[0][1])
        self.assertEqual(items[0][4]['brand'], 'growth')

    def test_shopee_passes_keyword_and_provenance_to_payload(self):
        collector = MagicMock()
        collector.fetch.return_value = [{
            'itemId': 1, 'shopId': 2, 'productName': 'Nike tênis', 'priceMin': '100',
            'priceDiscountRate': 30, 'productLink': 'https://shopee.example/item',
            'offerLink': 'https://shopee.example/offer', 'imageUrl': 'https://img.example/a.jpg',
        }]
        scraper = ShopeeScraper(client=MagicMock())
        scraper._collector = collector
        query = SearchQuery('shopee', 'nike tênis', 'radar_brand', brand='nike')

        result = scraper.scrape_search_queries((query,))

        collector.fetch.assert_called_once_with(keyword='nike tênis', limit=10, page=1)
        self.assertEqual(result[0]['search_provenance']['brand'], 'nike')
