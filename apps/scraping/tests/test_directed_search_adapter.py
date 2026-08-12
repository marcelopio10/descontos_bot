from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity
from apps.scraping.services.adapters import ScraperAdapter


class DirectedSearchAdapterTests(SimpleTestCase):
    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar')
    @patch('apps.scraping.services.adapters.build_opportunity_plan')
    def test_adapter_executes_directed_opportunities(self, build_plan, build_radar, _enabled, _category_enabled):
        opportunity = CommercialOpportunity('amazon', 'nike tenis', 'brand_product', 'radar_brand', brand='nike')
        build_radar.return_value = {'brands': [], 'categories': {}, 'price_bands': {}}
        build_plan.return_value.opportunities = (opportunity,)
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_search_queries.return_value = [
            {
                'external_id': 'directed-1',
                'title': 'Nike Tênis',
                'product_url': 'https://example.test/nike',
                'current_price': 199,
                'original_price': 399,
                'search_provenance': {'source_kind': 'radar_brand', 'query_text': 'nike tenis'},
            },
        ]

        result = ScraperAdapter('amazon', scraper).collect(max_pages=1)

        scraper.scrape_search_queries.assert_called_once_with((opportunity,))
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'radar_brand')
        self.assertTrue(result[0]['search_provenance']['opportunity_id'])
        self.assertEqual(len(result[0]['search_provenance']['query_hash']), 16)

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_adapter_keeps_legacy_fallback_only_when_explicitly_disabled(self, _enabled, _category_enabled):
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_daily_deals.return_value = [{'external_id': 'fallback-1'}]

        result = ScraperAdapter('amazon', scraper).collect(max_pages=2)

        scraper.scrape_daily_deals.assert_called_once_with(max_pages=2)
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'generic_fallback')
