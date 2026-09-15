from decimal import Decimal
from unittest.mock import Mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.mercadolivre_api_pipeline import MercadoLivreApiPipeline
from apps.marketplaces.services.mercadolivre_price_resolver import PriceSnapshot
from apps.marketplaces.services.mercadolivre_affiliate_adapter import AffiliateLinkResult
from apps.offers.models import Offer
from apps.scraping.models import ScrapingItemResult, ScrapingRun


class FakeSearchProvider:
    def __init__(self, candidates):
        self.candidates = candidates

    def search_many(self, _requests, *, max_pages):
        return self.candidates


class FakePriceResolver:
    def resolve(self, _item):
        return PriceSnapshot(
            current_price=Decimal('80.00'),
            original_price=Decimal('100.00'),
            discount_pct=Decimal('20.00'),
            currency_code='BRL',
            source='sale_price',
        )


class FakeClient:
    def get_seller(self, _seller_id):
        return {'id': 10, 'nickname': 'Loja', 'seller_reputation': {'level_id': 'green'}}


class FakeAffiliate:
    def __init__(self, generated=True):
        self.generated = generated
        self.calls = []

    def generate_result(self, original_url):
        self.calls.append(original_url)
        if self.generated:
            return AffiliateLinkResult('https://mercadolivre.com/sec/abc', True)
        return AffiliateLinkResult(original_url, False, 'credentials_missing')


class RaisingAffiliate(FakeAffiliate):
    def generate_result(self, original_url):
        self.calls.append(original_url)
        raise RuntimeError('motor temporariamente indisponível')


class MercadoLivreApiPipelineTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )
        self.run = ScrapingRun.objects.create(
            marketplace=self.marketplace,
            started_at=timezone.now(),
            provider='mercadolivre_api',
        )

    def _pipeline(self, candidate, affiliate=None):
        return MercadoLivreApiPipeline(
            marketplace=self.marketplace,
            run=self.run,
            max_pages=1,
            client=FakeClient(),
            search_provider=FakeSearchProvider([candidate]),
            price_resolver=FakePriceResolver(),
            affiliate_adapter=affiliate or FakeAffiliate(),
            observed_at=timezone.now(),
        )

    @override_settings(ML_API_ALLOWED_SELLER_LEVEL_IDS=('green',))
    def test_persists_original_before_generated_affiliate(self):
        affiliate = FakeAffiliate()
        result = self._pipeline({
            'id': 'MLB999',
            'title': 'Cafeteira',
            'permalink': 'https://www.mercadolivre.com.br/p/MLB999',
            'status': 'active',
            'condition': 'new',
            'available_quantity': 5,
            'seller': {'id': 10},
            '_category_hint': 'casa_cozinha',
            '_search_provenance': {'source_kind': 'category_target'},
        }, affiliate).run_collection()

        self.assertEqual(result.total_valid, 1)
        offer = Offer.objects.get(external_id='MLB999')
        self.assertEqual(offer.product_url, 'https://www.mercadolivre.com.br/p/MLB999')
        self.assertEqual(offer.affiliate_url, 'https://mercadolivre.com/sec/abc')
        self.assertEqual(affiliate.calls, [offer.product_url])
        self.assertEqual(
            ScrapingItemResult.objects.get(run=self.run, sequence=1).status,
            ScrapingItemResult.Status.ACCEPTED,
        )

    @override_settings(ML_API_ALLOWED_SELLER_LEVEL_IDS=('green',))
    def test_invalid_item_is_discarded_without_affiliate_call(self):
        affiliate = FakeAffiliate()
        result = self._pipeline({
            'id': 'MLB998',
            'title': 'Produto usado',
            'permalink': 'https://www.mercadolivre.com.br/p/MLB998',
            'status': 'active',
            'condition': 'used',
            'available_quantity': 5,
            'seller': {'id': 10},
            '_category_hint': 'casa_cozinha',
        }, affiliate).run_collection()

        self.assertEqual(result.total_discarded, 1)
        self.assertEqual(affiliate.calls, [])
        item = ScrapingItemResult.objects.get(run=self.run, sequence=1)
        self.assertEqual(item.status, ScrapingItemResult.Status.DISCARDED)
        self.assertEqual(item.reason_code, 'condition_not_new')

    @override_settings(ML_API_ALLOWED_SELLER_LEVEL_IDS=('green',))
    def test_affiliate_failure_keeps_original_for_next_retry(self):
        candidate = {
            'id': 'MLB997',
            'title': 'Cafeteira',
            'permalink': 'https://www.mercadolivre.com.br/p/MLB997',
            'status': 'active',
            'condition': 'new',
            'available_quantity': 5,
            'seller': {'id': 10},
            '_category_hint': 'casa_cozinha',
        }
        failed = RaisingAffiliate()
        first = self._pipeline(candidate, failed).run_collection()
        offer = Offer.objects.get(external_id='MLB997')
        item = ScrapingItemResult.objects.get(run=self.run, sequence=1)
        self.assertEqual(first.total_valid, 1)
        self.assertEqual(item.status, ScrapingItemResult.Status.AFFILIATE_FAILED)
        self.assertEqual(item.error_message, 'MLB997:RuntimeError')
        self.assertEqual(offer.affiliate_url, '')

        successful = FakeAffiliate()
        second = self._pipeline(candidate, successful).run_collection()
        offer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(second.total_valid, 1)
        self.assertEqual(successful.calls, [offer.product_url])
        self.assertEqual(item.status, ScrapingItemResult.Status.ACCEPTED)
        self.assertEqual(offer.affiliate_url, 'https://mercadolivre.com/sec/abc')
        self.assertEqual(Offer.objects.filter(external_id='MLB997').count(), 1)
