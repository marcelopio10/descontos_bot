from decimal import Decimal

from django.test import TestCase

from apps.curation.services.baseline_snapshot import serialize_offer_for_ai
from apps.curation.services.quality_score import quality_score_breakdown
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class EditorialPriorityTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp', code='whatsapp_main', target='test',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        marketplace = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre',
            base_url='https://mercadolivre.com.br', is_active=True,
        )
        from django.utils import timezone
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=marketplace, external_id='editorial-1',
            title='Bicicleta Spinning X11', normalized_title='bicicleta spinning x11',
            offer_hash='editorial-priority-1', slug='editorial-priority-1',
            current_price=Decimal('900'), original_price=Decimal('1200'), discount_pct=Decimal('25'),
            product_url='https://example.com/product', affiliate_url='https://example.com/affiliate',
            image_url='https://example.com/image.jpg', first_seen_at=now, last_seen_at=now,
            price_collected_at=now,
        )

    def test_spinning_is_low_priority_but_not_blacklisted(self):
        payload = serialize_offer_for_ai(self.offer)
        self.assertIn('low_priority_spinning', payload['editorial_flags'])
        breakdown = quality_score_breakdown(self.offer)
        self.assertIn('low_priority_spinning', breakdown.penalties)

    def test_generic_short_title_is_low_priority(self):
        self.offer.title = 'Oferta Especial'
        self.offer.normalized_title = 'oferta especial'
        self.offer.save(update_fields=['title', 'normalized_title'])
        payload = serialize_offer_for_ai(self.offer)
        self.assertIn('low_priority_generic', payload['editorial_flags'])
