from decimal import Decimal

from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer, PriceHistoryEntry
from apps.offers.services.normalizer import normalize_offer
from apps.offers.services.repository import save_normalized_offer


class SaveNormalizedOfferPriceHistoryTests(TestCase):
    """Sprint 5 / achado F, H5 (RESTR-05): histórico de preço interno."""

    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )

    def _payload(self, price: str) -> dict:
        return {
            'id': 'B0HISTTEST',
            'asin': 'B0HISTTEST',
            'nome': 'Produto com histórico',
            'preco': price,
            'link_direto': 'https://www.amazon.com.br/dp/B0HISTTEST',
        }

    def test_first_collection_creates_one_price_history_entry(self):
        normalized = normalize_offer(self.marketplace, self._payload('99,90'))

        offer, created = save_normalized_offer(normalized)

        self.assertTrue(created)
        self.assertEqual(PriceHistoryEntry.objects.filter(offer=offer).count(), 1)
        entry = PriceHistoryEntry.objects.get(offer=offer)
        self.assertEqual(entry.price, Decimal('99.90'))

    def test_second_collection_with_same_price_does_not_duplicate_entry(self):
        save_normalized_offer(normalize_offer(self.marketplace, self._payload('99,90')))
        offer, created = save_normalized_offer(normalize_offer(self.marketplace, self._payload('99,90')))

        self.assertFalse(created)
        self.assertEqual(PriceHistoryEntry.objects.filter(offer=offer).count(), 1)

    def test_collection_with_changed_price_adds_new_entry(self):
        save_normalized_offer(normalize_offer(self.marketplace, self._payload('99,90')))
        offer, created = save_normalized_offer(normalize_offer(self.marketplace, self._payload('79,90')))

        self.assertFalse(created)
        prices = list(
            PriceHistoryEntry.objects.filter(offer=offer).order_by('collected_at').values_list('price', flat=True),
        )
        self.assertEqual(prices, [Decimal('99.90'), Decimal('79.90')])

    def test_produto_canonico_id_is_persisted_on_the_offer(self):
        normalized = normalize_offer(self.marketplace, self._payload('99,90'))

        offer, _ = save_normalized_offer(normalized)

        self.assertEqual(offer.produto_canonico_id, 'amazon:B0HISTTEST')

    def test_produto_canonico_id_is_refreshed_on_update(self):
        offer, _ = save_normalized_offer(normalize_offer(self.marketplace, self._payload('99,90')))
        offer.produto_canonico_id = ''
        offer.save(update_fields=['produto_canonico_id'])

        offer, created = save_normalized_offer(normalize_offer(self.marketplace, self._payload('79,90')))

        self.assertFalse(created)
        self.assertEqual(offer.produto_canonico_id, 'amazon:B0HISTTEST')
