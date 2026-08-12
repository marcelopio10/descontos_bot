import hashlib
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.marketplaces.services.query_execution import execute_opportunities
from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity
from apps.marketplaces.services.source_contracts import SourceState


class QueryExecutionTests(SimpleTestCase):
    def test_successful_query_is_executed_and_provenance_is_attached(self):
        opportunity = CommercialOpportunity('mercadolivre', 'nike tenis', 'brand_product', 'radar_brand', brand='nike')
        source = MagicMock()
        source.execute.return_value = [{'external_id': '1', 'title': 'Nike tênis'}]

        result = execute_opportunities((opportunity,), source=source)

        source.execute.assert_called_once()
        self.assertEqual(result.results[0].state, SourceState.EXECUTED)
        self.assertEqual(result.offers[0]['search_provenance']['source_kind'], 'radar_brand')
        self.assertEqual(result.offers[0]['search_provenance']['query_text'], 'nike tenis')

    def test_exception_is_failed_and_does_not_call_generic_fallback(self):
        opportunity = CommercialOpportunity('amazon', 'lattafa perfume', 'brand_product', 'radar_brand', brand='lattafa')
        source = MagicMock()
        source.execute.side_effect = RuntimeError('captcha')

        result = execute_opportunities((opportunity,), source=source)

        self.assertEqual(result.results[0].state, SourceState.FAILED)
        self.assertEqual(result.results[0].error_code, 'source_exception')
        self.assertEqual(result.offers, ())
        self.assertNotIn('ofertas', [call.args[0].query_text for call in source.execute.call_args_list])

    def test_empty_result_is_explicitly_empty(self):
        opportunity = CommercialOpportunity('shopee', 'growth whey', 'brand_product', 'priority_catalog', brand='growth')
        source = MagicMock()
        source.execute.return_value = []

        result = execute_opportunities((opportunity,), source=source)

        self.assertEqual(result.results[0].state, SourceState.EMPTY)
        self.assertEqual(result.results[0].offers, ())
