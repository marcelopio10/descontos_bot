from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from scrapers.mercado_livre import MercadoLivreScraper
from scrapers.shopee import ShopeeScraper


class SourceBlockDetectionTests(SimpleTestCase):
    @patch.object(MercadoLivreScraper, 'fetch_with_retry')
    def test_mercado_livre_marks_account_verification_as_blocked(self, fetch):
        response = MagicMock(status_code=200, url='https://www.mercadolivre.com.br/gz/account-verification', text='suspicious traffic')
        fetch.return_value = response
        scraper = MercadoLivreScraper()

        self.assertEqual(scraper.get_html('https://lista.mercadolivre.com.br/nike-tenis'), '')
        self.assertTrue(scraper.blocked)
        self.assertIn('verificação', scraper.error_message)

    def test_shopee_graphql_error_stops_the_directed_cycle(self):
        collector = MagicMock()
        collector.fetch.side_effect = RuntimeError('ShopeeAffiliateError')
        scraper = ShopeeScraper(client=MagicMock())
        scraper._collector = collector

        result = scraper.scrape_search_queries((MagicMock(query_text='nike tenis', source_kind='radar_brand', brand='nike', category_code='', price_band='', marketplace='shopee'),))

        self.assertEqual(result, [])
        self.assertTrue(scraper.blocked)
        self.assertIn('indisponível', scraper.error_message)
