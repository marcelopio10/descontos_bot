from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting
from apps.social_posts.services.post_generator import generate_story_for_offer


class SocialPostSafetyTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
            is_active=True,
            affiliate_enabled=True,
            affiliate_tag='desconto.bot-20',
        )

    def _offer(self, title: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id='B0TESTE123',
            title=title,
            normalized_title=title.lower(),
            offer_hash='hash-adult-amazon',
            slug='adult-amazon',
            asin='B0TESTE123',
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=Decimal('46.00'),
            product_url='https://www.amazon.com.br/dp/B0TESTE123',
            affiliate_url='https://www.amazon.com.br/dp/B0TESTE123',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_story_generation_refuses_safety_blacklisted_offer_even_with_panel_override(self):
        Setting.objects.create(key='blacklist_terms', value='[]')
        offer = self._offer('Vibrador Massageador Íntimo Recarregável')

        with self.assertRaisesMessage(ValueError, 'Oferta bloqueada pela blacklist'):
            generate_story_for_offer(offer)
