from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.offers.services.normalizer import normalize_offer
from apps.curation.services.baseline_snapshot import serialize_offer_for_ai


class SearchProvenanceIntegrationTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(name='Amazon', code='amazon', is_active=True)

    def test_normalizer_keeps_sanitized_provenance_and_removes_private_fields(self):
        normalized = normalize_offer(self.marketplace, {
            'id': 'B000000000', 'title': 'Nike Tênis', 'current_price': '100',
            'original_price': '150', 'product_url': 'https://www.amazon.com.br/dp/B000000000',
            'image_url': 'https://img.example/a.jpg',
            'search_provenance': {'source_kind': 'radar_brand', 'brand': 'nike', 'raw_text': 'privado', 'group_jid': '123@g.us'},
        })
        self.assertEqual(normalized.raw_payload['search_provenance'], {'source_kind': 'radar_brand', 'brand': 'nike'})
        self.assertNotIn('raw_text', normalized.raw_payload)
        self.assertNotIn('group_jid', normalized.raw_payload)

    def test_snapshot_exposes_provenance(self):
        now = timezone.now()
        offer = Offer.objects.create(
            marketplace=self.marketplace, external_id='B000000000', title='Nike Tênis',
            normalized_title='nike tenis', offer_hash='prov-hash', slug='nike-tenis-prov',
            current_price=Decimal('100'), original_price=Decimal('150'), discount_pct=Decimal('33'),
            product_url='https://www.amazon.com.br/dp/B000000000', image_url='https://img.example/a.jpg',
            first_seen_at=now, last_seen_at=now, price_collected_at=now,
            raw_payload={'search_provenance': {'source_kind': 'radar_brand', 'brand': 'nike'}},
        )
        serialized = serialize_offer_for_ai(offer)
        self.assertEqual(serialized['search_provenance']['source_kind'], 'radar_brand')
