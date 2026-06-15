from decimal import Decimal

from django.test import SimpleTestCase

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.shopee_normalizer import (
    normalize_shopee_item,
    shopee_external_id,
)
from apps.offers.services.normalizer import OfferNormalizationError, build_offer_hash


class ShopeeNormalizerTests(SimpleTestCase):
    def setUp(self):
        # Marketplace não-salvo: normalize_offer só lê marketplace.code.
        self.marketplace = Marketplace(
            name='Shopee',
            code='shopee',
            base_url='https://shopee.com.br',
        )

    def _item(self, **overrides):
        item = {
            'itemId': 111,
            'shopId': 222,
            'productName': 'Fone Bluetooth X',
            'productLink': 'https://shopee.com.br/product/111',
            'offerLink': 'https://s.shopee.com.br/abc',
            'priceMin': '199.90',
            'priceDiscountRate': '50',
            'imageUrl': 'https://cf.shopee.com.br/img.jpg',
            'ratingStar': '4.5',
        }
        item.update(overrides)
        return item

    def test_external_id_combines_item_and_shop(self):
        self.assertEqual(shopee_external_id({'itemId': 1, 'shopId': 2}), '1:2')

    def test_dedup_hash_is_url_independent(self):
        first = normalize_shopee_item(self.marketplace, self._item())
        second = normalize_shopee_item(
            self.marketplace,
            self._item(
                productLink='https://shopee.com.br/product/111?campaign=xyz',
                offerLink='https://s.shopee.com.br/zzz',
            ),
        )
        self.assertEqual(first.offer_hash, second.offer_hash)
        self.assertEqual(first.offer_hash, build_offer_hash('shopee', '111:222', ''))

    def test_affiliate_url_uses_offer_link(self):
        normalized = normalize_shopee_item(self.marketplace, self._item())
        self.assertEqual(normalized.affiliate_url, 'https://s.shopee.com.br/abc')

    def test_original_price_is_derived_from_discount(self):
        normalized = normalize_shopee_item(
            self.marketplace,
            self._item(priceMin='100', priceDiscountRate='50'),
        )
        self.assertEqual(normalized.current_price, Decimal('100.00'))
        self.assertEqual(normalized.original_price, Decimal('200.00'))
        self.assertEqual(normalized.discount_pct, Decimal('50.00'))

    def test_no_original_price_without_reliable_discount(self):
        normalized = normalize_shopee_item(
            self.marketplace,
            self._item(priceMin='100', priceDiscountRate='0'),
        )
        self.assertIsNone(normalized.original_price)

    def test_missing_ids_are_rejected(self):
        with self.assertRaises(OfferNormalizationError):
            normalize_shopee_item(self.marketplace, self._item(itemId=None))
