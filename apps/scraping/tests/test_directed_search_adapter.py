from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.search_query_planner import SearchQuery
from apps.scraping.services import adapters
from apps.scraping.services.adapters import ScraperAdapter
from scrapers.category_targets import flatten_urls


class RadarOffMixin:
    """Desliga o radar de concorrente nos testes que cobrem os outros dois ramos.

    O radar é o terceiro ramo de `collect()` (2026-08-21) e lê `ObservedOfferLink`
    no banco. As classes abaixo são `SimpleTestCase`, sem banco: sem este patch a
    consulta seria barrada, cairia no `except` do próprio ramo e viraria um
    warning — silencioso o bastante para esconder um erro real depois.
    """

    def setUp(self):
        super().setUp()
        patcher = patch.object(adapters, '_competitor_radar_payloads', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)


class DirectedSearchAdapterTests(RadarOffMixin, SimpleTestCase):
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

    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar', side_effect=RuntimeError('radar fora do ar'))
    def test_directed_queries_failure_is_logged_instead_of_silenced(self, _build_radar, _enabled):
        """Achado B3: a exceção era engolida com `return ()` puro, sem rastro nenhum."""
        adapter = ScraperAdapter('amazon', MagicMock(blocked=False, error_message='', pages_scraped=0))

        with self.assertLogs('apps.scraping.services.adapters', level='WARNING') as captured:
            self.assertEqual(adapter._directed_queries(), ())

        self.assertIn('directed_queries_failed marketplace=amazon', captured.output[0])
        self.assertIn('radar fora do ar', captured.output[0])


class CategoryUnionCollectTests(RadarOffMixin, SimpleTestCase):
    """Achado B1 (2026-08-18) — coleta por união e filtros de categoria em `collect()`.

    Estes testes cobrem a lacuna B6: `test_category_filters.py` exercitava
    `_apply_category_filters` **em isolamento**, nunca a partir de `collect()`, e foi
    por isso que a regressão do commit 84e5071 passou despercebida.
    """

    TARGET_RULES = {
        'saude_suplementacao': {'min_discount': 30, 'max_price': 250.0, 'cycle_limit': 1},
        'casa_cozinha': {'min_discount': 15, 'max_price': 600.0, 'cycle_limit': 25},
    }

    def _adapter(self, scraper):
        return ScraperAdapter('amazon', scraper)

    def _scraper(self, *, directed=(), category=()):
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_search_queries.return_value = list(directed)
        scraper.scrape_categories.return_value = list(category)
        return scraper

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar', return_value={})
    @patch('apps.scraping.services.adapters.build_search_plan')
    def test_collect_runs_both_paths_and_merges(self, build_plan, _radar, _directed_on, _category_on):
        """Antes do B1 a categoria só rodava se a direcionada voltasse vazia."""
        query = SearchQuery('amazon', 'nike tênis', 'radar_brand', brand='nike')
        build_plan.return_value.directed_queries = (query,)
        scraper = self._scraper(
            directed=[{'external_id': 'directed-1', 'title': 'Nike', 'search_provenance': {'source_kind': 'radar_brand'}}],
            category=[{'external_id': 'cat-1', 'title': 'Panela', 'category_hint': 'casa_cozinha', 'desconto_pct': 40, 'preco': 120.0}],
        )

        with patch.object(adapters, 'get_targets', return_value=self.TARGET_RULES):
            result = self._adapter(scraper).collect(max_pages=1)

        scraper.scrape_search_queries.assert_called_once_with((query,))
        scraper.scrape_categories.assert_called_once()
        scraper.scrape_daily_deals.assert_not_called()
        self.assertEqual([p['external_id'] for p in result], ['directed-1', 'cat-1'])

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_collect_does_not_truncate_category_targets(self, _directed_off, _category_on):
        """Regressão do `targets[:DIRECTED_FALLBACK_CATEGORY_LIMIT]`.

        O corte fixo nas 2 primeiras URLs tornava as categorias do fim da lista
        inalcançáveis por construção — nenhum teste cobria isso.
        """
        scraper = self._scraper(category=[])
        expected = flatten_urls('amazon')
        self.assertGreater(len(expected), 2, 'fixture precisa de mais de 2 URLs para o teste ter sentido')

        self._adapter(scraper).collect(max_pages=1)

        passed = scraper.scrape_categories.call_args.args[0]
        self.assertEqual(len(passed), len(expected))
        self.assertEqual(
            [t[0] for t in passed],
            [t.category_code for t in expected],
        )
        # As categorias que o truncamento tornava inalcançáveis agora chegam ao scraper.
        self.assertIn('saude_suplementacao', {t[0] for t in passed})
        self.assertIn('moda_masculina', {t[0] for t in passed})

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_collect_applies_category_rules_and_logs_summary(self, _directed_off, _category_on):
        """`_apply_category_filters` agora roda no caminho real, com log de resumo."""
        scraper = self._scraper(category=[
            {'external_id': 'ok', 'category_hint': 'casa_cozinha', 'desconto_pct': 40, 'preco': 120.0},
            {'external_id': 'desconto-baixo', 'category_hint': 'saude_suplementacao', 'desconto_pct': 10, 'preco': 100.0},
            {'external_id': 'caro', 'category_hint': 'saude_suplementacao', 'desconto_pct': 50, 'preco': 900.0},
            {'external_id': 'suplemento-1', 'category_hint': 'saude_suplementacao', 'desconto_pct': 50, 'preco': 100.0},
            {'external_id': 'suplemento-2', 'category_hint': 'saude_suplementacao', 'desconto_pct': 50, 'preco': 100.0},
            {'external_id': 'sem-regra', 'category_hint': 'categoria_desconhecida'},
        ])

        with patch.object(adapters, 'get_targets', return_value=self.TARGET_RULES):
            with self.assertLogs('apps.scraping.services.adapters', level='INFO') as captured:
                result = self._adapter(scraper).collect(max_pages=1)

        kept = [p['external_id'] for p in result]
        self.assertEqual(kept, ['ok', 'suplemento-1', 'sem-regra'])
        # cycle_limit=1 corta o segundo suplemento; min_discount e max_price cortam os outros.
        self.assertNotIn('suplemento-2', kept)
        summary = [line for line in captured.output if 'category_scraping_summary' in line]
        self.assertTrue(summary, 'o log category_scraping_summary precisa voltar a sair')
        self.assertIn('kept=3', summary[0])
        self.assertIn('saude_suplementacao:min_discount', summary[0])
        self.assertIn('saude_suplementacao:max_price', summary[0])
        self.assertIn('saude_suplementacao:cycle_limit', summary[0])

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=True)
    @patch('apps.scraping.services.adapters.build_search_radar', return_value={})
    @patch('apps.scraping.services.adapters.build_search_plan')
    def test_duplicate_across_paths_keeps_signals_from_both(self, build_plan, _radar, _directed_on, _category_on):
        """A mesma oferta pelas duas vias: provenance da direcionada + hint da categoria."""
        build_plan.return_value.directed_queries = (SearchQuery('amazon', 'tramontina oferta', 'radar_brand', brand='tramontina'),)
        scraper = self._scraper(
            directed=[{'external_id': 'dup', 'search_provenance': {'source_kind': 'radar_brand', 'brand': 'tramontina'}, 'desconto_pct': 40, 'preco': 120.0}],
            category=[{'external_id': 'dup', 'category_hint': 'casa_cozinha', 'desconto_pct': 40, 'preco': 120.0}],
        )

        with patch.object(adapters, 'get_targets', return_value=self.TARGET_RULES):
            result = self._adapter(scraper).collect(max_pages=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['search_provenance']['brand'], 'tramontina')
        self.assertEqual(result[0]['category_hint'], 'casa_cozinha')

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=True)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_daily_deals_remains_last_resort_when_both_paths_are_empty(self, _directed_off, _category_on):
        scraper = self._scraper(category=[])
        scraper.scrape_daily_deals.return_value = [{'external_id': 'daily-1'}]

        result = self._adapter(scraper).collect(max_pages=3)

        scraper.scrape_daily_deals.assert_called_once_with(max_pages=3)
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'generic_fallback')


class CompetitorRadarBranchTests(SimpleTestCase):
    """Terceiro ramo da união (2026-08-21): ofertas vindas do radar de concorrente."""

    def _scraper(self):
        scraper = MagicMock(blocked=False, error_message='', pages_scraped=1)
        scraper.scrape_search_queries.return_value = []
        scraper.scrape_categories.return_value = []
        return scraper

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_radar_payloads_join_the_union(self, _directed_off, _category_off):
        scraper = self._scraper()
        radar = [{
            'id': 'MLB123', 'nome': 'Chinelo Reserva', 'preco': 57.0, 'desconto_pct': 55,
            'search_provenance': {'source_kind': 'competitor_radar', 'marketplace': 'mercadolivre'},
        }]

        with patch.object(adapters, '_competitor_radar_payloads', return_value=radar):
            result = ScraperAdapter('mercadolivre', scraper).collect(max_pages=1)

        # Sem o radar, os dois ramos vazios cairiam no `scrape_daily_deals`.
        scraper.scrape_daily_deals.assert_not_called()
        self.assertEqual([p['id'] for p in result], ['MLB123'])
        self.assertEqual(result[0]['search_provenance']['source_kind'], 'competitor_radar')

    @patch('apps.scraping.services.adapters._category_scraping_enabled', return_value=False)
    @patch('apps.scraping.services.adapters._directed_search_enabled', return_value=False)
    def test_radar_failure_is_logged_and_does_not_break_collection(self, _directed_off, _category_off):
        scraper = self._scraper()
        scraper.scrape_daily_deals.return_value = [{'external_id': 'daily-1'}]

        with patch(
            'apps.market_intel.services.competitor_radar.radar_enabled',
            side_effect=RuntimeError('banco fora'),
        ):
            with self.assertLogs('apps.scraping.services.adapters', level='WARNING') as captured:
                result = ScraperAdapter('mercadolivre', scraper).collect(max_pages=1)

        self.assertIn('competitor_radar_payloads_failed', ' '.join(captured.output))
        self.assertEqual(result[0]['external_id'], 'daily-1')
