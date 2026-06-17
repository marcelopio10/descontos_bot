from unittest.mock import patch

from django.test import SimpleTestCase

from apps.scraping.services import adapters


class CategoryFilterTests(SimpleTestCase):
    def test_category_filters_accept_shopee_english_price_discount_keys(self):
        with patch.object(
            adapters,
            'get_targets',
            return_value={
                'tecnologia_cotidiana': {
                    'min_discount': 20,
                    'max_price': 100,
                    'cycle_limit': 2,
                },
            },
        ):
            payload = {
                'category_hint': 'tecnologia_cotidiana',
                'discount_pct': 35,
                'price': 79.9,
                'title': 'Fone bluetooth Shopee',
            }

            self.assertEqual(
                adapters._apply_category_filters('shopee', [payload]),
                [payload],
            )
