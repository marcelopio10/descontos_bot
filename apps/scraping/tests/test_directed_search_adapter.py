from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.search_query_planner import SearchQuery
from apps.scraping.services.adapters import ScraperAdapter


class DirectedSearchAdapterTests(SimpleTestCase):
    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar', return_value={})
    @patch('apps.scraping.services.adapters.build_search_plan')
    def test_adapter_executes_directed_queries_before_category_fallback(self, build_plan, _build_radar, _enabled, _category_enabled):
        query = SearchQuery('amazon', 'nike tênis', 'radar_brand', brand='nike')
        build_plan.return_value.directed_queries = (query,)
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_search_queries.return_value = [
            {'external_id': 'directed-1', 'title': 'Nike Tênis', 'search_provenance': {'source_kind': 'radar_brand'}},
        ]
        adapter = ScraperAdapter('amazon', scraper)

        result = adapter.collect(max_pages=1)

        scraper.scrape_search_queries.assert_called_once_with((query,))
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'radar_brand')

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_adapter_keeps_existing_daily_fallback_when_directed_search_is_disabled(self, _enabled, _category_enabled):
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_daily_deals.return_value = [{'external_id': 'fallback-1'}]
        adapter = ScraperAdapter('amazon', scraper)

        result = adapter.collect(max_pages=2)

        scraper.scrape_daily_deals.assert_called_once_with(max_pages=2)
        self.assertEqual(result[0]['external_id'], 'fallback-1')
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'generic_fallback')
