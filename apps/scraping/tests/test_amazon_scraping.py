import os
import random
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.marketplaces.models import Marketplace
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping
from scrapers.amazon import (
    BACKOFF_CAP_SECONDS,
    BACKOFF_JITTER_SECONDS,
    MAX_ATTEMPTS,
    AmazonScraper,
    build_from_env,
)


class AmazonScraperConfigTests(SimpleTestCase):
    def test_build_from_env_accepts_public_settings_variable_name(self):
        with patch.dict(os.environ, {'AMAZON_AFFILIATE_TAG': 'tag-correta-20'}, clear=True):
            scraper = build_from_env()

        self.assertEqual(scraper.associate_tag, 'tag-correta-20')


class AmazonScraperSessionTests(SimpleTestCase):
    def test_session_is_built_via_shared_impersonation_helper(self):
        """AmazonScraper deve delegar a criação da sessão HTTP ao helper
        compartilhado de scrapers/base.py (curl_cffi com impersonação
        'chrome124', fallback gracioso para requests puro)."""
        with patch('scrapers.amazon.build_impersonated_session') as mock_builder:
            mock_builder.return_value = MagicMock()
            AmazonScraper()

        mock_builder.assert_called_once_with('chrome124')


class AmazonScraperBackoffTests(SimpleTestCase):
    def test_get_html_retries_with_exponential_backoff_and_bounded_jitter(self):
        scraper = AmazonScraper(rng=random.Random(0))
        scraper.session = MagicMock()
        scraper.session.get.return_value = MagicMock(status_code=500)

        sleeps: list[float] = []
        with patch('scrapers.amazon.time.sleep', side_effect=sleeps.append):
            result = scraper.get_html('https://www.amazon.com.br/dp/B000000000')

        self.assertEqual(result, '')
        self.assertEqual(scraper.session.get.call_count, MAX_ATTEMPTS)
        # 1ª tentativa não dorme; as demais (MAX_ATTEMPTS - 1) dormem com
        # backoff exponencial (base 2**(n-1), com cap) + jitter aleatório
        # limitado a BACKOFF_JITTER_SECONDS.
        self.assertEqual(len(sleeps), MAX_ATTEMPTS - 1)
        for attempt, backoff in enumerate(sleeps, start=2):
            base = min(2 ** (attempt - 1), BACKOFF_CAP_SECONDS)
            self.assertGreaterEqual(backoff, base)
            self.assertLess(backoff, base + BACKOFF_JITTER_SECONDS)
        # Backoffs crescem estritamente entre tentativas (2s < 4s < 8s de base).
        self.assertLess(sleeps[0], sleeps[1])
        self.assertLess(sleeps[1], sleeps[2])

    def test_get_html_backoff_is_deterministic_given_seeded_rng(self):
        def run_with_seed(seed: int) -> list[float]:
            scraper = AmazonScraper(rng=random.Random(seed))
            scraper.session = MagicMock()
            scraper.session.get.return_value = MagicMock(status_code=500)
            sleeps: list[float] = []
            with patch('scrapers.amazon.time.sleep', side_effect=sleeps.append):
                scraper.get_html('https://www.amazon.com.br/dp/B000000000')
            return sleeps

        self.assertEqual(run_with_seed(42), run_with_seed(42))

    def test_get_html_returns_immediately_on_success_without_sleeping(self):
        scraper = AmazonScraper(rng=random.Random(0))
        scraper.session = MagicMock()
        scraper.session.get.return_value = MagicMock(status_code=200, text='<html>ok</html>')

        with patch('scrapers.amazon.time.sleep') as mock_sleep:
            result = scraper.get_html('https://www.amazon.com.br/dp/B000000000')

        self.assertEqual(result, '<html>ok</html>')
        self.assertEqual(scraper.session.get.call_count, 1)
        mock_sleep.assert_not_called()


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
