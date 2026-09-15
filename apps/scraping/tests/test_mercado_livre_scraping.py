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

    def test_get_html_rejects_external_initial_url_before_transport(self):
        scraper = MercadoLivreScraper()
        scraper.session = MagicMock()

        self.assertEqual(scraper.get_html('https://evil.example/private'), '')
        scraper.session.get.assert_not_called()

    def test_get_html_follows_only_allowlisted_https_redirects(self):
        redirect = MagicMock(status_code=302, headers={
            'Location': 'https://www.mercadolivre.com.br/ofertas?page=1',
        })
        success = MagicMock(status_code=200, headers={}, text='<html>ok</html>')
        scraper = MercadoLivreScraper()
        scraper.session = MagicMock()
        scraper.session.get.side_effect = [redirect, success]

        self.assertEqual(scraper.get_html('https://meli.la/abc'), '<html>ok</html>')
        self.assertEqual(scraper.session.get.call_count, 2)
        for call in scraper.session.get.call_args_list:
            self.assertFalse(call.kwargs['allow_redirects'])

    def test_get_html_does_not_fetch_an_external_redirect_target(self):
        redirect = MagicMock(status_code=302, headers={
            'Location': 'https://evil.example/private',
        })
        scraper = MercadoLivreScraper()
        scraper.session = MagicMock()
        scraper.session.get.return_value = redirect

        self.assertEqual(scraper.get_html('https://meli.la/abc'), '')
        scraper.session.get.assert_called_once()
        self.assertFalse(scraper.session.get.call_args.kwargs['allow_redirects'])

    def test_fetch_with_retry_disables_redirects_by_default(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        scraper = MercadoLivreScraper()

        scraper.fetch_with_retry(
            session,
            'https://meli.la/abc',
            headers={},
        )

        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_get_html_sanitizes_unexpected_transport_exception(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError('secret-sentinel')
        scraper = MercadoLivreScraper()
        scraper.session = session

        with patch('scrapers.base.time.sleep'), self.assertLogs('scrapers.mercado_livre', level='ERROR') as logs:
            result = scraper.get_html('https://meli.la/abc')

        self.assertEqual(result, '')
        self.assertEqual(scraper.error_message, 'Falha inesperada na coleta do Mercado Livre.')
        self.assertNotIn('secret-sentinel', '\n'.join(logs.output))

    def test_fetch_with_retry_sanitizes_arbitrary_exception_when_called_directly(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError('RAW_URL_TEXT_SENTINEL')
        scraper = MercadoLivreScraper()

        with patch('scrapers.base.time.sleep'), self.assertLogs('scrapers.base', level='WARNING') as logs:
            with self.assertRaises(RuntimeError) as context:
                scraper.fetch_with_retry(session, 'https://meli.la/abc', headers={})

        self.assertEqual(str(context.exception), 'Falha HTTP na coleta.')
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)
        self.assertNotIn('RAW_URL_TEXT_SENTINEL', '\n'.join(logs.output))

    def test_fetch_rejects_encoded_control_and_path_before_transport(self):
        for url in (
            'https://www.mercadolivre.com.br/ofertas%0a',
            'https://www.mercadolivre.com.br/ofertas%2Fprivado',
        ):
            with self.subTest(url=url):
                scraper = MercadoLivreScraper()
                scraper.session = MagicMock()

                self.assertEqual(scraper.get_html(url), '')
                scraper.session.get.assert_not_called()

    def test_fetch_status_subclass_is_not_logged_as_raw_value(self):
        class SneakyInt(int):
            def __str__(self):
                return 'STATUS_SECRET_SENTINEL'

        session = MagicMock()
        session.get.return_value = MagicMock(status_code=SneakyInt(500))
        scraper = MercadoLivreScraper()

        with patch('scrapers.base.time.sleep'), self.assertLogs('scrapers.base', level='WARNING') as logs:
            with self.assertRaises(RuntimeError) as context:
                scraper.fetch_with_retry(session, 'https://meli.la/abc', headers={})

        self.assertEqual(str(context.exception), 'Resposta HTTP inválida na coleta.')
        self.assertNotIn('STATUS_SECRET_SENTINEL', '\n'.join(logs.output))


class MercadoLivreCookieAlertTests(SimpleTestCase):
    """`_gerar_link_afiliado_oficial` usa uma sessão ISOLADA (achado 2026-07-22:
    `self.session`, compartilhada com a raspagem de listagem, acumula cookies
    novos — inclusive um `_csrf` fresco do ML — que quebram o CSRF estático do
    `.env` e derrubam a chamada mesmo com credenciais válidas). Por isso os
    testes aqui mockam `build_impersonated_session` (o construtor da sessão
    isolada), não mais `scraper.session` diretamente.
    """

    def _build_scraper_with_fake_credentials(self) -> MercadoLivreScraper:
        return MercadoLivreScraper(
            affiliate_tag=FAKE_AFFILIATE_TAG,
            ml_cookie=FAKE_ML_COOKIE,
            ml_csrf=FAKE_ML_CSRF,
        )

    def _patch_affiliate_session(self, response: MagicMock):
        return patch('scrapers.mercado_livre.build_impersonated_session', return_value=MagicMock(post=MagicMock(return_value=response)))

    def test_reactive_alert_fires_once_per_cycle_not_per_offer(self):
        """Simula 3 ofertas no mesmo ciclo, todas rejeitadas com HTTP 401
        (cookie expirado). O alerta ao operador deve disparar só na primeira."""
        scraper = self._build_scraper_with_fake_credentials()
        response = MagicMock(ok=False, status_code=401)

        with self._patch_affiliate_session(response), patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            resultados = [
                scraper._gerar_link_afiliado_oficial(
                    f'https://produto.mercadolivre.com.br/MLB-100000000{i}-x',
                )
                for i in range(3)
            ]

        # sem link de afiliado, cai no fallback (retorna o permalink original)
        self.assertEqual(resultados, [
            'https://produto.mercadolivre.com.br/MLB-1000000000-x',
            'https://produto.mercadolivre.com.br/MLB-1000000001-x',
            'https://produto.mercadolivre.com.br/MLB-1000000002-x',
        ])
        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs.get('categoria'), 'ml_cookie_expirado')

    def test_reactive_alert_never_leaks_the_real_cookie_or_csrf_value(self):
        scraper = self._build_scraper_with_fake_credentials()
        response = MagicMock(ok=False, status_code=403)

        with self._patch_affiliate_session(response), patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/MLB-1000000001-y')

        mensagem = mock_alert.call_args.args[0]
        self.assertNotIn(FAKE_ML_COOKIE, mensagem)
        self.assertNotIn(FAKE_ML_CSRF, mensagem)

    def test_missing_credentials_trigger_alert_once_per_cycle(self):
        """Sem ML_COOKIE/ML_CSRF_TOKEN/tag configurados, o alerta também
        dispara (via _exibir_alerta_cookie), mas só uma vez por instância."""
        scraper = MercadoLivreScraper()

        with patch('scrapers.mercado_livre.build_impersonated_session') as mock_builder, \
                patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/MLB-1000000002-a')
            scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/MLB-1000000003-b')

        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs.get('categoria'), 'ml_cookie_expirado')
        # a sessão de afiliado nunca deveria ter sido criada sem credenciais
        mock_builder.assert_not_called()

    def test_successful_affiliate_response_does_not_alert(self):
        scraper = self._build_scraper_with_fake_credentials()
        response = MagicMock(
            ok=True,
            status_code=200,
            json=lambda: {'short_url': 'https://mercadolivre.com/sec/fake-short'},
        )

        with self._patch_affiliate_session(response), patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
            resultado = scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/MLB-1000000004-c')

        self.assertEqual(resultado, 'https://mercadolivre.com/sec/fake-short')
        mock_alert.assert_not_called()

    def test_alert_flag_resets_across_scraper_instances(self):
        """A dedupe é por instância (= por ciclo, já que cada ciclo cria um
        scraper novo via build_from_env()) — uma nova instância deve poder
        alertar de novo."""
        response = MagicMock(ok=False, status_code=401)
        for _ in range(2):
            scraper = self._build_scraper_with_fake_credentials()
            with self._patch_affiliate_session(response), patch('scrapers.mercado_livre.enviar_alerta_operador') as mock_alert:
                scraper._gerar_link_afiliado_oficial('https://produto.mercadolivre.com.br/MLB-1000000005-d')
            mock_alert.assert_called_once()


class SocialCardScrapingTests(SimpleTestCase):
    """Radar de concorrente (2026-08-21): resolver `meli.la` na vitrine de afiliado.

    A vitrine lista o catálogo inteiro de quem publicou; o anúncio do link é o que
    o `og:title` nomeia. O ID do item vem do href do card — nunca do `og:image`,
    cujo nome de arquivo carrega o ID do *asset* (às vezes até de outro site, um
    `MLA...`), e não o do anúncio.
    """

    CARD_TEMPLATE = (
        '<div class="poly-card">'
        '<a class="poly-component__title" href="{href}">{titulo}</a>'
        '<div class="poly-price__current"><span class="andes-money-amount__fraction">{preco}</span></div>'
        '<s class="andes-money-amount--previous"><span class="andes-money-amount__fraction">{de}</span></s>'
        '<img class="poly-component__picture" src="{imagem}"/>'
        '</div>'
    )

    def _html(self, og_title, cards):
        corpo = ''.join(self.CARD_TEMPLATE.format(**card) for card in cards)
        return f'<html><head><meta property="og:title" content="{og_title}"/></head><body>{corpo}</body></html>'

    def _scraper(self, html):
        scraper = MercadoLivreScraper()
        scraper.get_html = MagicMock(return_value=html)
        scraper.is_blocked = MagicMock(return_value=False)
        scraper._gerar_link_afiliado_oficial = MagicMock(side_effect=lambda url: f'{url}#afiliado')
        return scraper

    def _card(self, titulo, item, preco='100', de='200'):
        return {
            'titulo': titulo,
            'href': f'https://produto.mercadolivre.com.br/{item}-slug-_JM',
            'preco': preco,
            'de': de,
            'imagem': 'https://http2.mlstatic.com/D_NQ_NP_1-MLA99981972913_112025-O.webp',
        }

    def test_escolhe_o_card_do_og_title_e_nao_o_primeiro(self):
        html = self._html('Relógio Casio G-Shock', [
            self._card('Outro Produto Da Vitrine', 'MLB-1111111111'),
            self._card('Relógio Casio G-Shock', 'MLB-2222222222', preco='248', de='519'),
        ])

        payload = self._scraper(html).scrape_social_card('https://meli.la/abc')

        self.assertEqual(payload['id'], 'MLB2222222222')
        self.assertEqual(payload['nome'], 'Relógio Casio G-Shock')
        self.assertEqual(payload['preco'], 248.0)
        self.assertEqual(payload['preco_original'], 519.0)

    def test_id_vem_do_href_e_nao_do_asset_da_imagem(self):
        """O `og:image` da vitrine chega a apontar para asset `MLA...`, de outro site."""
        html = self._html('Par Retrovisor Triumph', [self._card('Par Retrovisor Triumph', 'MLB-3656481579')])

        payload = self._scraper(html).scrape_social_card('https://meli.la/abc')

        self.assertEqual(payload['id'], 'MLB3656481579')

    def test_sem_casamento_de_titulo_nao_resolve(self):
        """Chutar o card em destaque trocava o produto em silêncio.

        Casos reais de 2026-08-21: mensagem de "micro-ondas consul cms23ab"
        resolveu num "Micro-ondas MTO30", e "Insider Light T-Shirt" na "Daily
        T-shirt". A oferta é real, mas não é a que o grupo anunciou — o que
        derruba a premissa do radar.
        """
        html = self._html('Micro-ondas Consul 23L CMS23AB', [self._card('Micro-ondas MTO30 20L', 'MLB-4444444444')])

        self.assertIsNone(self._scraper(html).scrape_social_card('https://meli.la/abc'))

    def test_vitrine_sem_alvo_no_og_title_nao_resolve(self):
        """`og:title` vira "Minhas recomendações" quando o link aponta para a raiz."""
        html = self._html('Minhas recomendações', [self._card('Produto Qualquer Da Vitrine', 'MLB-5555555555')])

        self.assertIsNone(self._scraper(html).scrape_social_card('https://meli.la/abc'))

    def test_titulo_do_card_mais_longo_que_o_og_title_casa(self):
        html = self._html('Camiseta Daily T-shirt Insider', [
            self._card('Camiseta Daily T-shirt Insider Masculina Preta P', 'MLB-3962940727', preco='69', de='139'),
        ])

        payload = self._scraper(html).scrape_social_card('https://meli.la/abc')

        self.assertEqual(payload['id'], 'MLB3962940727')

    def test_pagina_sem_card_devolve_none(self):
        payload = self._scraper('<html><body>vitrine vazia</body></html>').scrape_social_card('https://meli.la/abc')

        self.assertIsNone(payload)

    def test_html_bloqueado_marca_o_scraper_como_bloqueado(self):
        scraper = self._scraper('<html>captcha</html>')
        scraper.is_blocked = MagicMock(return_value=True)

        self.assertIsNone(scraper.scrape_social_card('https://meli.la/abc'))
        self.assertTrue(scraper.blocked)

    def test_gera_link_de_afiliado_nosso_para_o_anuncio(self):
        """O link do concorrente é descartado: publicamos com a nossa tag."""
        html = self._html('Chinelo Reserva', [self._card('Chinelo Reserva', 'MLB-5555555555', preco='57', de='129')])

        payload = self._scraper(html).scrape_social_card('https://meli.la/abc')

        self.assertEqual(
            payload['link_afiliado'],
            'https://produto.mercadolivre.com.br/MLB-5555555555-slug-_JM#afiliado',
        )

    def test_href_externo_e_descartado_antes_do_motor_afiliado(self):
        card = self._card('Produto perigoso', 'MLB-5555555555')
        card['href'] = 'javascript:alert(1)//MLB-5555555555'
        scraper = self._scraper(self._html('Produto perigoso', [card]))

        self.assertIsNone(scraper.scrape_social_card('https://meli.la/abc'))

    def test_href_com_query_ou_controle_codificado_e_descartado_antes_do_motor(self):
        for href in (
            'https://produto.mercadolivre.com.br/MLB-5555555555?x=\n',
            'https://produto.mercadolivre.com.br/MLB-5555555555?x=%0A',
            'https://produto.mercadolivre.com.br/MLB-5555555555?',
            'https://produto.mercadolivre.com.br/MLB-5555555555#frag',
        ):
            with self.subTest(href=href):
                card = self._card('Produto perigoso', 'MLB-5555555555')
                card['href'] = href
                scraper = self._scraper(self._html('Produto perigoso', [card]))

                self.assertIsNone(scraper.scrape_social_card('https://meli.la/abc'))
