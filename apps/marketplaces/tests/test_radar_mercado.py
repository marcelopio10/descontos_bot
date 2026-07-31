from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.marketplaces.services.radar_mercado import collect_radar_mercado
from apps.offers.models import Category


class FakeProductOfferCollector:
    """Coletor falso: devolve nós fixos por keyword, sem chamar a API real."""

    def __init__(self, nodes_by_keyword=None, *, raise_for_keywords=None):
        self.nodes_by_keyword = nodes_by_keyword or {}
        self.raise_for_keywords = set(raise_for_keywords or ())
        self.calls: list[dict] = []

    def fetch(self, *, keyword=None, limit=None, page=1, product_cat_id=None, sort_type=None, list_type=None):
        self.calls.append(
            {'keyword': keyword, 'limit': limit, 'sort_type': sort_type, 'list_type': list_type}
        )
        if keyword in self.raise_for_keywords:
            raise RuntimeError(f'falha simulada para {keyword}')
        return self.nodes_by_keyword.get(keyword, [])


class RadarMercadoGateTests(TestCase):
    """Sprint 6 / Tarefa 6.1 (achado P7) — gate por SHOPEE_AFFILIATE_ENABLED."""

    def test_disabled_by_default_returns_neutral_result_without_calling_collector(self):
        # SHOPEE_AFFILIATE_ENABLED não setado -> default False, estado real de produção hoje.
        collector = FakeProductOfferCollector({'Casa e Cozinha': [{'sales': 999, 'productName': 'X'}]})
        Category.objects.create(code='casa_cozinha_qa', name='Casa e Cozinha', weight=10, is_active=True)

        result = collect_radar_mercado(collector=collector)

        self.assertFalse(result.enabled)
        self.assertEqual(result.category_scores, {})
        self.assertEqual(result.product_scores, {})
        self.assertEqual(result.sample_size, 0)
        self.assertEqual(collector.calls, [])  # nenhuma chamada à API/coletor

    @override_settings(SHOPEE_AFFILIATE_ENABLED=False)
    def test_explicitly_disabled_returns_neutral_result(self):
        collector = FakeProductOfferCollector({'Casa e Cozinha': [{'sales': 10}]})
        Category.objects.create(code='casa_cozinha_qa', name='Casa e Cozinha', weight=10, is_active=True)

        result = collect_radar_mercado(collector=collector)

        self.assertFalse(result.enabled)
        self.assertEqual(collector.calls, [])
        self.assertIn('SHOPEE_AFFILIATE_ENABLED=false', result.limitations)


class RadarMercadoCollectionTests(TestCase):
    """Sprint 6 / Tarefa 6.1 — coleta habilitada, escore_venda por categoria/produto."""

    def setUp(self):
        self.casa = Category.objects.create(code='casa_cozinha_qa', name='Casa e Cozinha', weight=10, is_active=True)
        self.moda = Category.objects.create(code='moda_feminina_qa', name='Moda Feminina', weight=9, is_active=True)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_category_scores_normalized_by_max_sales(self):
        collector = FakeProductOfferCollector(
            {
                'Casa e Cozinha': [
                    {'sales': 100, 'productName': 'Air fryer'},
                    {'sales': 50, 'productName': 'Panela'},
                ],
                'Moda Feminina': [
                    {'sales': 10, 'productName': 'Vestido'},
                ],
            }
        )

        result = collect_radar_mercado(categories=[self.casa, self.moda], collector=collector)

        self.assertTrue(result.enabled)
        self.assertEqual(result.sample_size, 3)
        self.assertEqual(set(result.categories_covered), {'casa_cozinha_qa', 'moda_feminina_qa'})
        # casa_cozinha soma 150 vendas, moda_feminina soma 10 -> normalizado pelo máximo (150).
        self.assertEqual(result.category_scores['casa_cozinha_qa'], 1.0)
        self.assertAlmostEqual(result.category_scores['moda_feminina_qa'], 10 / 150, places=4)
        self.assertIn('Air fryer', result.product_scores)
        self.assertEqual(result.product_scores['Air fryer'], 1.0)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_does_not_trust_api_sort_order_reranks_locally_by_sales_field(self):
        # Mesmo que a API devolva os nós em qualquer ordem, o escore_venda vem
        # da reordenação local por `sales` (ver docstring do módulo: sortType
        # da Shopee não tem semântica de "mais vendidos" confirmada).
        collector = FakeProductOfferCollector(
            {
                'Casa e Cozinha': [
                    {'sales': 5, 'productName': 'Produto pouco vendido'},
                    {'sales': 500, 'productName': 'Produto mais vendido'},
                ],
            }
        )

        result = collect_radar_mercado(categories=[self.casa], collector=collector)

        self.assertEqual(result.product_scores['Produto mais vendido'], 1.0)
        self.assertLess(result.product_scores['Produto pouco vendido'], result.product_scores['Produto mais vendido'])

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_one_category_failure_does_not_break_the_whole_radar(self):
        collector = FakeProductOfferCollector(
            nodes_by_keyword={'Moda Feminina': [{'sales': 20, 'productName': 'Blusa'}]},
            raise_for_keywords={'Casa e Cozinha'},
        )

        result = collect_radar_mercado(categories=[self.casa, self.moda], collector=collector)

        self.assertTrue(result.enabled)
        self.assertEqual(result.categories_covered, ['moda_feminina_qa'])
        self.assertNotIn('casa_cozinha_qa', result.category_scores)
        self.assertEqual(result.category_scores['moda_feminina_qa'], 1.0)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_empty_results_produce_neutral_scores_without_error(self):
        collector = FakeProductOfferCollector({})

        result = collect_radar_mercado(categories=[self.casa], collector=collector)

        self.assertTrue(result.enabled)
        # Categoria consultada mas sem itens devolvidos: fica explícita com
        # escore 0.0 (transparência no payload/auditoria), não some do dict.
        self.assertEqual(result.category_scores, {'casa_cozinha_qa': 0.0})
        self.assertEqual(result.product_scores, {})
        self.assertEqual(result.sample_size, 0)


class ColetarRadarMercadoCommandTests(TestCase):
    def test_command_reports_disabled_state_without_calling_api(self):
        out = StringIO()
        call_command('coletar_radar_mercado', stdout=out)
        self.assertIn('Radar desligado', out.getvalue())
