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

    def test_mercado_livre_skips_free_text_directed_search(self):
        """Achado B2 (2026-08-18): não existe URL de busca por texto scrapável no ML.

        Verificado ao vivo — `lista.mercadolivre.com.br` só responde autenticado e
        a página virou React streaming SSR (zero cards no HTML servido);
        `/ofertas?q=` ignora o `q` e devolveria ofertas genéricas disfarçadas de
        busca direcionada. A contenção é pular: o adapter então cai no fallback de
        categoria/daily deals, que funciona. Ver a docstring do método e
        `docs/DIAGNOSTICO_ENVIOS_COLETA_2026-08-18.md`.
        """
        query = SearchQuery('mercadolivre', 'growth whey', 'priority_catalog', brand='growth')
        scraper = MercadoLivreScraper()

        with self.assertLogs('scrapers.mercado_livre', level='WARNING') as captured:
            result = scraper.scrape_search_queries((query,))

        self.assertEqual(result, [])
        self.assertIn('ml_directed_search_skipped', captured.output[0])
        # Nenhuma requisição HTTP foi feita e nada foi marcado como bloqueado.
        self.assertEqual(scraper.pages_scraped, 0)
        self.assertFalse(scraper.blocked)

    def test_mercado_livre_without_queries_is_silent(self):
        self.assertEqual(MercadoLivreScraper().scrape_search_queries(()), [])

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
