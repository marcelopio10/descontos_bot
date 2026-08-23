from django.test import SimpleTestCase

from apps.marketplaces.services.search_provenance import (
    ALLOWED_SEARCH_SOURCES,
    sanitize_search_provenance,
)
from apps.marketplaces.services.search_query_planner import (
    SearchPlan,
    SearchQuery,
    build_search_plan,
)


class SearchQueryPlannerTests(SimpleTestCase):
    def test_builds_directed_queries_with_budget_and_sources(self):
        radar = {
            'brands': [
                {'family': 'moda', 'term': 'Nike', 'observed_count': 39},
                {'family': 'suplementos', 'term': 'Growth', 'observed_count': 0},
            ],
            'categories': {'categoria:moda': 199},
            'price_bands': {'0_50': 149},
            'marketplaces': {'mercadolivre': 324},
            'coupon_signals': {'SEMPREMODA': 121},
        }

        plan = build_search_plan(radar, marketplaces=('mercadolivre',), max_queries=10)

        self.assertIsInstance(plan, SearchPlan)
        self.assertTrue(plan.queries)
        self.assertTrue(any(query.query_text.startswith('nike') for query in plan.queries))
        self.assertTrue(any(query.source_kind == 'radar_category' for query in plan.queries))
        self.assertTrue(any(query.source_kind == 'radar_price_band' for query in plan.queries))
        self.assertTrue(all(query.marketplace == 'mercadolivre' for query in plan.queries))
        self.assertTrue(all(query.source_kind in ALLOWED_SEARCH_SOURCES for query in plan.queries))
        self.assertLessEqual(len(plan.fallback_queries), 1)

    def test_rejects_unsafe_or_generic_query_values(self):
        with self.assertRaises(ValueError):
            SearchQuery(
                marketplace='mercadolivre',
                query_text='CUPOM',
                source_kind='radar_coupon_signal',
            )

        with self.assertRaises(ValueError):
            SearchQuery(
                marketplace='mercadolivre',
                query_text='nike @g.us',
                source_kind='radar_brand',
            )

    def test_sanitizes_provenance_without_raw_observer_data(self):
        result = sanitize_search_provenance({
            'source_kind': 'radar_brand',
            'query_text': 'nike tênis desconto',
            'brand': 'nike',
            'raw_text': 'não pode sair',
            'group_jid': '123@g.us',
            'url': 'https://privado.example/teste',
        })

        self.assertEqual(result, {
            'source_kind': 'radar_brand',
            'query_text': 'nike tênis desconto',
            'brand': 'nike',
        })
        self.assertNotIn('raw_text', result)
        self.assertNotIn('group_jid', result)
        self.assertNotIn('url', result)


class BrandQueryDiversityTests(SimpleTestCase):
    """Achado 2026-08-21: o termo de produto era fixo por família, então TODA
    marca de moda virava "<marca> tênis" e o plano de busca inteiro puxava
    tênis — 13% de tudo que foi coletado em 7 dias."""

    def _moda_radar(self, *terms):
        return {
            'brands': [{'family': 'moda', 'term': term, 'observed_count': 0} for term in terms],
            'categories': {},
            'price_bands': {},
        }

    def test_marcas_da_mesma_familia_nao_buscam_todas_o_mesmo_produto(self):
        radar = self._moda_radar('Nike', 'Adidas', 'Puma', 'Olympikus')

        plan = build_search_plan(radar, marketplaces=('mercadolivre',), max_queries=20)

        produtos = {
            query.query_text.split(' ', 1)[1]
            for query in plan.queries
            if query.brand
        }
        self.assertGreater(len(produtos), 1)
        self.assertEqual(len([q for q in plan.queries if q.query_text.endswith('tênis')]), 1)

    def test_plano_e_deterministico_entre_execucoes(self):
        radar = self._moda_radar('Nike', 'Adidas', 'Puma')

        primeiro = build_search_plan(radar, marketplaces=('mercadolivre',), max_queries=20)
        segundo = build_search_plan(radar, marketplaces=('mercadolivre',), max_queries=20)

        self.assertEqual(
            [query.query_text for query in primeiro.queries],
            [query.query_text for query in segundo.queries],
        )

    def test_familia_sem_lista_propria_mantem_o_termo_generico(self):
        radar = {
            'brands': [{'family': 'nicho_novo', 'term': 'MarcaX', 'observed_count': 0}],
            'categories': {},
            'price_bands': {},
        }

        plan = build_search_plan(radar, marketplaces=('mercadolivre',), max_queries=10)

        self.assertIn('marcax oferta', [query.query_text for query in plan.queries])
