import os
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.marketplaces.models import Marketplace
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping
from scrapers.amazon import build_from_env


class AmazonScraperConfigTests(SimpleTestCase):
    def test_build_from_env_accepts_public_settings_variable_name(self):
        with patch.dict(os.environ, {'AMAZON_AFFILIATE_TAG': 'tag-correta-20'}, clear=True):
            scraper = build_from_env()

        self.assertEqual(scraper.associate_tag, 'tag-correta-20')


class EmptyAmazonScrapeStatusTests(TestCase):
    def test_empty_amazon_scrape_is_not_marked_success(self):
        marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
            is_active=True,
        )

        class EmptyAdapter:
            blocked = False
            error_message = ''

            def collect(self, max_pages):
                return []

        with patch('apps.scraping.services.runner.build_adapter', return_value=EmptyAdapter()), \
                patch('apps.scraping.services.runner.alertar_scraper_zero_ofertas') as mock_alert:
            result = run_marketplace_scraping(marketplace, max_pages=1)

        self.assertEqual(result.total_collected, 0)
        self.assertEqual(result.total_valid, 0)
        self.assertEqual(result.run.status, ScrapingRun.RunStatus.FAILED)
        self.assertIn('Amazon retornou 0 ofertas', result.run.error_message)
        # Guarda: nunca deve disparar um envio real de Telegram durante os testes.
        mock_alert.assert_called_once()
