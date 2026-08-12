from django.test import SimpleTestCase

from apps.marketplaces.services.commercial_opportunity import (
    CommercialOpportunity,
    build_opportunity_plan,
)


class CommercialOpportunityTests(SimpleTestCase):
    def test_builds_product_queries_from_observed_brands_and_catalog(self):
        radar = {
            'brands': [
                {'family': 'moda', 'term': 'adidas', 'observed_count': 329},
                {'family': 'suplementos', 'term': 'growth', 'observed_count': 0},
                {'family': 'perfumes_arabes', 'term': 'lattafa', 'observed_count': 14},
            ],
            'categories': {'categoria:moda': 1803, 'categoria:beleza': 900},
            'price_bands': {'100_250': 1686},
        }

        plan = build_opportunity_plan(radar, marketplace='mercadolivre', limit=8)
        texts = {item.query_text for item in plan.opportunities}

        self.assertIn('adidas tenis', texts)
        self.assertIn('growth whey', texts)
        self.assertIn('lattafa perfume', texts)
        self.assertNotIn('adidas oferta', texts)
        self.assertNotIn('moda', texts)
        self.assertNotIn('ofertas 100 250', texts)

    def test_rejects_generic_or_incomplete_queries(self):
        with self.assertRaises(ValueError):
            CommercialOpportunity(
                marketplace='mercadolivre',
                query_text='lg oferta',
                intent='brand_product',
                source_kind='radar_brand',
            )

        with self.assertRaises(ValueError):
            CommercialOpportunity(
                marketplace='mercadolivre',
                query_text='CUPOM',
                intent='coupon_signal',
                source_kind='radar_coupon_signal',
            )

    def test_plan_marks_unplannable_signal_instead_of_falling_back(self):
        plan = build_opportunity_plan(
            {'brands': [], 'categories': {'categoria:moda': 10}, 'price_bands': {}},
            marketplace='amazon',
            limit=20,
        )

        self.assertTrue(plan.opportunities)
        self.assertTrue(all(item.source_kind == 'priority_catalog' for item in plan.opportunities))
        self.assertEqual(plan.unplannable[0]['reason'], 'category_without_product')
