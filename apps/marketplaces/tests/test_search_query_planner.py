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
