from django.test import SimpleTestCase

from apps.marketplaces.services.firecrawl_source import FirecrawlConfig, FirecrawlSource
from apps.marketplaces.services.source_contracts import SourceQuery, SourceState


class FirecrawlSourceTests(SimpleTestCase):
    def setUp(self):
        self.query = SourceQuery('mercadolivre', 'nike tenis', 'op-1', 'radar_brand', 'hash-1')

    def test_disabled_by_default_is_explicitly_blocked(self):
        result = FirecrawlSource().execute(self.query)
        self.assertEqual(result.state, SourceState.BLOCKED)
        self.assertEqual(result.error_code, 'firecrawl_disabled')

    def test_enabled_source_sanitizes_public_candidate(self):
        source = FirecrawlSource(
            config=FirecrawlConfig(enabled=True),
            scraper=lambda query, timeout: [{'title': 'Nike', 'product_url': 'https://example.test', 'secret': 'remove'}],
        )
        result = source.execute(self.query)
        self.assertEqual(result.state, SourceState.EXECUTED)
        self.assertEqual(result.offers[0], {'title': 'Nike', 'product_url': 'https://example.test'})
