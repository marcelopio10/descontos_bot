from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from scrapers.mercado_livre import MercadoLivreScraper


class MercadoLivreScraperSessionTests(SimpleTestCase):
    def test_session_is_built_via_shared_impersonation_helper(self):
        """MercadoLivreScraper deve delegar a criação da sessão HTTP ao mesmo
        helper de impersonação TLS usado pelo AmazonScraper (scrapers/base.py),
        em vez de `requests.Session()` puro."""
        with patch('scrapers.mercado_livre.build_impersonated_session') as mock_builder:
            mock_builder.return_value = MagicMock()
            MercadoLivreScraper()

        mock_builder.assert_called_once_with('chrome124')
