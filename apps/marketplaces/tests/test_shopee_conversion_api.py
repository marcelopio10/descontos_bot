from datetime import datetime, timezone

from django.test import SimpleTestCase

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient
from apps.marketplaces.services.shopee_conversion_api import (
    fetch_conversion_report,
    normalize_conversion_report,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.query = ''

    def execute(self, query, variables=None):
        self.query = query
        assert variables is None
        return self.response


class ShopeeConversionApiTests(SimpleTestCase):
    def test_fetch_conversion_report_uses_bounded_literal_window_and_pagination(self):
        client = FakeClient({'conversionReport': {'nodes': [], 'pageInfo': {'hasNextPage': False}}})
        result = fetch_conversion_report(
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 2, tzinfo=timezone.utc),
            limit=10,
            scroll_id='next-page',
            client=client,
        )

        assert result['conversionReport']['pageInfo']['hasNextPage'] is False
        assert 'conversionReport' in client.query
        assert 'purchaseTimeStart:' in client.query
        assert 'limit: 10' in client.query
        assert 'scrollId: "next-page"' in client.query

    def test_normalize_conversion_report_preserves_commission_product_and_no_channel_claim(self):
        payload = {
        'conversionReport': {
            'nodes': [{
                'clickTime': 1785600000,
                'purchaseTime': 1785600300,
                'conversionId': 123,
                'conversionStatus': 'COMPLETED',
                'grossCommission': '10.00',
                'estimatedTotalCommission': '11.00',
                'totalCommission': '11.00',
                'netCommission': '9.50',
                'utmContent': 'unknown',
                'referrer': 'direct',
                'orders': [{
                    'orderId': 'order-1',
                    'orderStatus': 'COMPLETED',
                    'items': [{
                        'shopId': 456,
                        'itemId': 789,
                        'itemName': 'Produto teste',
                        'itemPrice': '49.90',
                        'actualAmount': '39.90',
                        'refundAmount': '0',
                        'qty': 1,
                        'itemCommission': '11.00',
                        'itemTotalCommission': '11.00',
                        'attributionType': 'DIRECT',
                        'channelType': 'UNKNOWN',
                    }],
                }],
            }],
            'pageInfo': {'hasNextPage': False, 'scrollId': ''},
        },
        }

        rows = normalize_conversion_report(payload)

        assert rows == [{
            'conversion_id': '123',
            'order_id': 'order-1',
            'item_id': '789',
            'shop_id': '456',
            'external_ref': '789:456',
            'product_title': 'Produto teste',
            'purchase_time': 1785600300,
            'status': 'COMPLETED',
            'quantity': 1,
            'revenue_brl': '39.90',
            'commission_brl': '11.00',
            'channel': None,
            'utm_content': 'unknown',
            'attribution_type': 'DIRECT',
        }]
