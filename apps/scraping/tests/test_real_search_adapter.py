from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity
from apps.scraping.services.adapters import ScraperAdapter


class RealSearchAdapterTests(SimpleTestCase):
    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar')
    @patch('apps.scraping.services.adapters.build_opportunity_plan')
    def test_query_failure_does_not_fall_back_to_legacy_categories(self, build_plan, build_radar, _directed, _category):
        opportunity = CommercialOpportunity('amazon', 'lattafa perfume', 'brand_product', 'radar_brand', brand='lattafa')
        build_radar.return_value = {'brands': [], 'categories': {}, 'price_bands': {}}
        build_plan.return_value.opportunities = (opportunity,)
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=0)
        scraper.scrape_search_queries.return_value = []

        result = ScraperAdapter('amazon', scraper).collect(max_pages=2)

        scraper.scrape_search_queries.assert_called_once()
        scraper.scrape_categories.assert_not_called()
        scraper.scrape_daily_deals.assert_not_called()
        self.assertEqual(result, [])

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar', side_effect=RuntimeError('observer indisponível'))
    def test_planner_failure_is_exposed_and_does_not_use_legacy_fallback(self, _radar, _directed, _category):
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=0)
        adapter = ScraperAdapter('mercadolivre', scraper)

        with self.assertRaises(RuntimeError):
            adapter.collect(max_pages=2)

        scraper.scrape_daily_deals.assert_not_called()
