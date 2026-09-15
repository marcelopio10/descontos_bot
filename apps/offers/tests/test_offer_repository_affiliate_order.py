from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.offers.services.normalizer import normalize_offer
from apps.offers.services.repository import OfferRepository
from apps.scraping.models import ScrapingItemResult, ScrapingRun


class OfferRepositoryAffiliateOrderTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )
        self.run = ScrapingRun.objects.create(
            marketplace=self.marketplace,
            started_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            provider='mercadolivre_api',
        )
        self.normalized = normalize_offer(self.marketplace, {
            'id': 'MLB123',
            'nome': 'Produto',
            'preco': '80.00',
            'preco_original': '100.00',
            'link_direto': 'https://www.mercadolivre.com.br/p/MLB123',
            'collection_source': 'mercadolivre_api',
            'seller_id': '1',
            'currency_code': 'BRL',
            'status': 'active',
            'condition': 'new',
            'available_quantity': 2,
        })

    def test_original_is_saved_before_affiliate_and_retry_is_idempotent(self):
        repository = OfferRepository()
        observed_at = datetime(2026, 9, 12, tzinfo=timezone.utc)
        offer, item, created = repository.save_original(
            self.normalized,
            run=self.run,
            sequence=1,
            observed_at=observed_at,
            source='radar_brand',
        )
        self.assertTrue(created)
        self.assertEqual(offer.product_url, 'https://www.mercadolivre.com.br/p/MLB123')
        self.assertEqual(offer.affiliate_url, '')
        self.assertEqual(item.status, ScrapingItemResult.Status.PENDING)

        repository.attach_affiliate(
            offer,
            affiliate_url='https://mercadolivre.com/sec/abc',
            generated=True,
            run_item=item,
            observed_at=observed_at,
        )
        offer.refresh_from_db()
        self.assertEqual(offer.affiliate_url, 'https://mercadolivre.com/sec/abc')
        self.assertEqual(item.status, ScrapingItemResult.Status.ACCEPTED)

        second, second_item, second_created = repository.save_original(
            self.normalized,
            run=self.run,
            sequence=2,
            observed_at=observed_at,
            source='radar_brand',
        )
        second.refresh_from_db()
        self.assertFalse(second_created)
        self.assertEqual(Offer.objects.filter(external_id='MLB123').count(), 1)
        self.assertEqual(second.affiliate_url, 'https://mercadolivre.com/sec/abc')
        self.assertEqual(second_item.status, ScrapingItemResult.Status.PENDING)

    def test_derived_url_is_reconciled_when_canonical_permalink_arrives(self):
        repository = OfferRepository()
        observed_at = datetime(2026, 9, 12, tzinfo=timezone.utc)
        derived, _item, created = repository.save_original(
            self.normalized,
            run=self.run,
            sequence=10,
            observed_at=observed_at,
            source='api_fallback',
        )
        self.assertTrue(created)
        canonical = normalize_offer(self.marketplace, {
            'id': 'MLB123',
            'nome': 'Produto',
            'preco': '80.00',
            'preco_original': '100.00',
            'link_direto': 'https://produto.mercadolivre.com.br/MLB-123-produto',
            'collection_source': 'mercadolivre_api',
        })

        reconciled, _second_item, second_created = repository.save_original(
            canonical,
            run=self.run,
            sequence=11,
            observed_at=observed_at,
            source='category_target',
        )

        self.assertFalse(second_created)
        self.assertEqual(reconciled.pk, derived.pk)
        self.assertEqual(reconciled.product_url, canonical.product_url)
        self.assertEqual(Offer.objects.filter(external_id='MLB123').count(), 1)
