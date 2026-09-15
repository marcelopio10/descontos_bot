from decimal import Decimal
from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.marketplaces.services.mercadolivre_eligibility import MercadoLivreOfferEligibilityPolicy
from apps.offers.services.normalizer import NormalizedOffer


class MercadoLivreEligibilityTests(SimpleTestCase):
    def _offer(self, **changes):
        values = {
            'marketplace': Mock(code='mercadolivre'),
            'external_id': 'MLB1',
            'title': 'Produto',
            'normalized_title': 'produto',
            'offer_hash': 'hash',
            'produto_canonico_id': 'mercadolivre:MLB1',
            'current_price': Decimal('80.00'),
            'original_price': Decimal('100.00'),
            'discount_pct': Decimal('20.00'),
            'product_url': 'https://www.mercadolivre.com.br/p/MLB1',
            'affiliate_url': '',
            'asin': '',
            'price_collected_at': None,
            'image_url': '',
            'raw_payload': {},
            'seller_id': '123',
            'seller_name': 'Loja',
            'currency_code': 'BRL',
            'listing_status': 'active',
            'condition': 'new',
            'available_quantity': 10,
            'collection_source': 'mercadolivre_api',
        }
        values.update(changes)
        return NormalizedOffer(**values)

    def test_accepts_valid_offer(self):
        result = MercadoLivreOfferEligibilityPolicy().evaluate(
            self._offer(),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20, 'max_price': 800},
        )
        self.assertTrue(result.eligible)

    def test_rejects_inactive_and_ineligible_seller(self):
        policy = MercadoLivreOfferEligibilityPolicy()
        inactive = policy.evaluate(
            self._offer(listing_status='paused'),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20},
        )
        seller = policy.evaluate(
            self._offer(),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'red'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20},
        )
        self.assertEqual(inactive.reason_code, 'inactive')
        self.assertEqual(seller.reason_code, 'seller_not_eligible')

    def test_rejects_missing_reference_and_unavailable_item(self):
        policy = MercadoLivreOfferEligibilityPolicy()
        missing = policy.evaluate(
            self._offer(original_price=None, discount_pct=Decimal('0')),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20},
        )
        unavailable = policy.evaluate(
            self._offer(available_quantity=0),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20},
        )
        self.assertEqual(missing.reason_code, 'missing_price_reference')
        self.assertEqual(unavailable.reason_code, 'unavailable')

    def test_rejects_invalid_available_quantity(self):
        policy = MercadoLivreOfferEligibilityPolicy()
        for quantity in ('bogus', -1, 1.5, True):
            with self.subTest(quantity=quantity):
                result = policy.evaluate(
                    self._offer(available_quantity=quantity),
                    category_code='casa_cozinha',
                    seller_reputation={'level_id': 'green'},
                    allowed_seller_levels={'green'},
                    category_rules={'min_discount': 20},
                )
                self.assertFalse(result.eligible)
                self.assertEqual(result.reason_code, 'invalid_quantity')

    def test_rejects_category_without_configured_rules(self):
        result = MercadoLivreOfferEligibilityPolicy().evaluate(
            self._offer(),
            category_code='categoria_desconhecida',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={},
        )
        self.assertEqual(result.reason_code, 'category_not_allowed')

    def test_enforces_category_cycle_limit(self):
        result = MercadoLivreOfferEligibilityPolicy().evaluate(
            self._offer(),
            category_code='casa_cozinha',
            seller_reputation={'level_id': 'green'},
            allowed_seller_levels={'green'},
            category_rules={'min_discount': 20, 'cycle_limit': 1},
            category_count=1,
        )
        self.assertEqual(result.reason_code, 'cycle_limit')
