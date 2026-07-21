from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from scrapers.mercado_livre import MercadoLivreScraper

# Valores FALSOS de fixture — nunca lidos do .env real. Usados só para exercitar
# a lógica de dedupe/alerta; não representam credenciais verdadeiras do ML.
FAKE_ML_COOKIE = 'fake-session-cookie-value; _csrf=fake-csrf-marker'
FAKE_ML_CSRF = 'fake-csrf-token-1234'
FAKE_AFFILIATE_TAG = 'fake-affiliate-tag'


class MercadoLivreScraperSessionTests(SimpleTestCase):
    def test_session_is_built_via_shared_impersonation_helper(self):
        """MercadoLivreScraper deve delegar a criação da sessão HTTP ao mesmo
        helper de impersonação TLS usado pelo AmazonScraper (scrapers/base.py),
        em vez de `requests.Session()` puro."""
        with patch('scrapers.mercado_livre.build_impersonated_session') as mock_builder:
            mock_builder.return_value = MagicMock()
            MercadoLivreScraper()

        mock_builder.assert_called_once_with('chrome124')


class MercadoLivreCookieAlertTests(SimpleTestCase):
    def _build_scraper_with_fake_credentials(self) -> MercadoLivreScraper:
        scraper = MercadoLivreScraper(
            affiliate_tag=FAKE_AFFILIATE_TAG,
            ml_cookie=FAKE_ML_COOKIE,
            ml_csrf=FAKE_ML_CSRF,
        )
        scraper.session = MagicMock()
        return scraper

    def test_reactive_alert_fires_once_per_cycle_not_per_offer(self):
        """Simula 3 ofertas no mesmo ciclo, todas rejeitadas com HTTP 401
        (cookie expirado). O alerta ao operador deve disparar só na primeira."""
        scraper = self._build_scraper_with_fake_credentials()
        scraper.session.post.return_value = MagicMock(ok=False, status_code=401)

        with patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            resultados = [
                scraper._gerar_link_afiliado_oficial(f'https://produto.mercadolivre.com.br/x{i}')
                for i in range(3)
            ]

        # sem link de afiliado, cai no fallback (retorna o permalink original)
        self.assertEqual(resultados, [
            'https://produto.mercadolivre.com.br/x0',
            'https://produto.mercadolivre.com.br/x1',
            'https://produto.mercadolivre.com.br/x2',
        ])
        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs.get('categoria'), 'ml_cookie_expirado')

    def test_reactive_alert_never_leaks_the_real_cookie_or_csrf_value(self):
        scraper = self._build_scraper_with_fake_credentials()
        scraper.session.post.return_value = MagicMock(ok=False, status_code=403)

        with patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/y')

        mensagem = mock_alert.call_args.args[0]
        self.assertNotIn(FAKE_ML_COOKIE, mensagem)
        self.assertNotIn(FAKE_ML_CSRF, mensagem)

    def test_missing_credentials_trigger_alert_once_per_cycle(self):
        """Sem ML_COOKIE/ML_CSRF_TOKEN/tag configurados, o alerta também
        dispara (via _exibir_alerta_cookie), mas só uma vez por instância."""
        scraper = MercadoLivreScraper()
        scraper.session = MagicMock()

        with patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/a')
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/b')

        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs.get('categoria'), 'ml_cookie_expirado')
        # a chamada HTTP nunca deveria ter sido tentada sem credenciais
        scraper.session.post.assert_not_called()

    def test_successful_affiliate_response_does_not_alert(self):
        scraper = self._build_scraper_with_fake_credentials()
        scraper.session.post.return_value = MagicMock(
            ok=True,
            json=lambda: {'short_url': 'https://mercadolivre.com/sec/fake-short'},
        )

        with patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            resultado = scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/c')

        self.assertEqual(resultado, 'https://mercadolivre.com/sec/fake-short')
        mock_alert.assert_not_called()

    def test_alert_flag_resets_across_scraper_instances(self):
        """A dedupe é por instância (= por ciclo, já que cada ciclo cria um
        scraper novo via build_from_env()) — uma nova instância deve poder
        alertar de novo."""
        for _ in range(2):
            scraper = self._build_scraper_with_fake_credentials()
            scraper.session.post.return_value = MagicMock(ok=False, status_code=401)
            with patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
                scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/d')
            mock_alert.assert_called_once()
