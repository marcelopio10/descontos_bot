from django.test import SimpleTestCase

from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity
from apps.marketplaces.services.commercial_validator import validate_commercial_candidate


class CommercialValidatorTests(SimpleTestCase):
    def setUp(self):
        self.opportunity = CommercialOpportunity('mercadolivre', 'nike tenis', 'brand_product', 'radar_brand', brand='nike')

    def test_accepts_relevant_offer_with_evidence(self):
        result = validate_commercial_candidate({
            'title': 'Tênis Nike Revolution',
            'product_url': 'https://example.test/nike',
            'current_price': 199,
            'original_price': 399,
            'rating': 4.8,
            'sales': 5000,
        }, self.opportunity)
        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, 'accepted')

    def test_rejects_unrelated_title_and_missing_reference_price(self):
        result = validate_commercial_candidate({
            'title': 'Caminhão dinossauro',
            'product_url': 'https://example.test/item',
            'current_price': 99,
        }, self.opportunity)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, 'query_title_mismatch')

    def test_rejects_invalid_or_missing_url(self):
        result = validate_commercial_candidate({'title': 'Tênis Nike', 'current_price': 99}, self.opportunity)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, 'missing_product_url')

    def test_rejects_other_brand_that_only_contains_brand_characters(self):
        opportunity = CommercialOpportunity('amazon', 'lg fone', 'brand_product', 'radar_brand', brand='lg')
        result = validate_commercial_candidate({
            'title': 'JBL Fone de Ouvido Bluetooth',
            'product_url': 'https://example.test/jbl',
            'current_price': 199,
            'original_price': 299,
        }, opportunity)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, 'query_title_mismatch')
