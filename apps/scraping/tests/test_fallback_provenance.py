from unittest.mock import patch

from django.test import SimpleTestCase

from apps.scraping.services.adapters import ScraperAdapter


class FallbackProvenanceTests(SimpleTestCase):
    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_daily_payload_without_origin_is_marked_as_generic_fallback(self, _directed, _category):
        scraper = type('FakeScraper', (), {
            'blocked': False,
            'error_message': '',
            'pages_scraped': 1,
            'scrape_daily_deals': lambda self, max_pages: [{'external_id': 'x'}],
        })()
        result = ScraperAdapter('mercadolivre', scraper).collect(max_pages=1)
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'generic_fallback')
