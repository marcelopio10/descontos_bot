from decimal import Decimal
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.mercadolivre_price_resolver import MercadoLivrePriceResolver


class MercadoLivrePriceResolverTests(SimpleTestCase):
    @override_settings(ML_API_CONTEXTUAL_PRICE_ENABLED=True, ML_API_CONTEXT='channel_marketplace')
    def test_contextual_price_wins_and_calculates_discount(self):
        client = Mock()
        client.get_sale_price.return_value = {
            'amount': 80,
            'regular_amount': 100,
            'currency_id': 'BRL',
            'reference_date': '2026-09-12T10:00:00Z',
        }
        resolver = MercadoLivrePriceResolver(client)

        result = resolver.resolve({'id': 'MLB1', 'price': 90, 'original_price': 120, 'currency_id': 'BRL'})

        self.assertEqual(result.current_price, Decimal('80.00'))
        self.assertEqual(result.original_price, Decimal('100.00'))
        self.assertEqual(result.discount_pct, Decimal('20.00'))
        self.assertEqual(result.source, 'sale_price')

    @override_settings(ML_API_CONTEXTUAL_PRICE_ENABLED=True)
    def test_404_contextual_price_falls_back_to_item_price(self):
        from apps.marketplaces.services.mercadolivre_api_client import MercadoLivreApiError

        client = Mock()
        client.get_sale_price.side_effect = MercadoLivreApiError(
            'not found', status_code=404, endpoint='/items/{ITEM_ID}/sale_price',
        )
        result = MercadoLivrePriceResolver(client).resolve({
            'id': 'MLB1', 'price': 75, 'base_price': 100, 'currency_id': 'BRL',
        })

        self.assertEqual(result.current_price, Decimal('75.00'))
        self.assertEqual(result.original_price, Decimal('100.00'))
        self.assertEqual(result.error_code, 'contextual_price_unavailable')

    @override_settings(ML_API_CONTEXTUAL_PRICE_ENABLED=True)
    def test_auth_error_is_not_hidden(self):
        from apps.marketplaces.services.mercadolivre_api_client import MercadoLivreApiError

        client = Mock()
        client.get_sale_price.side_effect = MercadoLivreApiError(
            'forbidden', status_code=403, endpoint='/items/{ITEM_ID}/sale_price', auth_error=True,
        )
        with self.assertRaises(MercadoLivreApiError):
            MercadoLivrePriceResolver(client).resolve({'id': 'MLB1', 'price': 75, 'currency_id': 'BRL'})
