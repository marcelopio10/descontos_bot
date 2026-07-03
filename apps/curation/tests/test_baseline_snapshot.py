from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.baseline_snapshot import build_baseline_snapshot, serialize_offer_for_ai
from apps.curation.services.selector import SelectionConfig
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Category, Offer


class BaselineSnapshotTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
            is_active=True,
        )
        self.category = Category.objects.create(code='tecnologia', name='Tecnologia', weight=10)
        self.channel = SocialChannel.objects.create(
            name='WhatsApp',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            category=self.category,
            external_id='echo-dot',
            title='Echo Dot 5ª geração com Alexa',
            normalized_title='echo dot 5 geracao com alexa',
            offer_hash='hash-baseline-1',
            slug='echo-dot-5',
            current_price=Decimal('249.90'),
            original_price=Decimal('499.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
            review_rating=Decimal('4.80'),
            review_count=1200,
        )

    def test_serialize_offer_includes_quality_score_breakdown(self):
        payload = serialize_offer_for_ai(self.offer)

        self.assertEqual(payload['offer_id'], self.offer.id)
        self.assertEqual(payload['marketplace_code'], 'amazon')
        self.assertIn('score', payload['baseline'])
        self.assertIn('components', payload['baseline'])
        self.assertIn('classification', payload['baseline'])
        self.assertIsInstance(payload['baseline']['score'], float)

    def test_build_baseline_snapshot_uses_selector_eligibility_and_counts(self):
        config = SelectionConfig(
            global_limit=20,
            marketplace_limit=10,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=70,
            exposure_quota_enabled=False,
        )

        snapshot = build_baseline_snapshot(self.channel, config=config, candidate_limit=10)

        self.assertEqual(snapshot['candidate_count'], 1)
        self.assertEqual(snapshot['marketplace_counts'], {'amazon': 1})
        self.assertIn(snapshot['offers'][0]['baseline']['decision'], {'publicar', 'prioritizar'})
        self.assertIn('quality_score_breakdown', snapshot)
