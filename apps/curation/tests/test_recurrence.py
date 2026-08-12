from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.recurrence import recurrence_score_multiplier, recurrence_signal
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.delivery import _should_republish_after_improvement
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class RecurrencePolicyTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp', code='whatsapp_main', target='test',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre',
            base_url='https://mercadolivre.com.br', is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace, external_id='ML-1',
            title='Bicicleta Spinning X11', normalized_title='bicicleta spinning x11',
            offer_hash='recurrence-offer-1', slug='recurrence-offer-1',
            produto_canonico_id='ML-X11', current_price=Decimal('900'),
            original_price=Decimal('1200'), discount_pct=Decimal('25'),
            product_url='https://example.com/product', affiliate_url='https://example.com/affiliate',
            image_url='https://example.com/image.jpg', first_seen_at=now, last_seen_at=now,
            price_collected_at=now,
        )

    def _sent(self, sent_at, *, offer=None, suffix=''):
        offer = offer or self.offer
        return Delivery.objects.create(
            offer=offer, social_channel=self.channel,
            message='Oferta R$ 900,00', delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=sent_at,
        )

    def _same_family_offer(self):
        return Offer.objects.create(
            marketplace=self.marketplace, external_id='ML-2',
            title='Bicicleta Spinning X11 vendedor 2', normalized_title='bicicleta spinning x11 vendedor 2',
            offer_hash='recurrence-offer-2', slug='recurrence-offer-2',
            produto_canonico_id='ML-X11', current_price=Decimal('900'),
            original_price=Decimal('1200'), discount_pct=Decimal('25'),
            product_url='https://example.com/product-2', affiliate_url='https://example.com/affiliate-2',
            image_url='https://example.com/image-2.jpg', first_seen_at=timezone.now(),
            last_seen_at=timezone.now(), price_collected_at=timezone.now(),
        )

    def test_recent_send_is_blocked_by_cooldown(self):
        now = timezone.now()
        self._sent(now - timedelta(hours=24))
        signal = recurrence_signal(self.offer, self.channel, now=now)
        self.assertTrue(signal.blocked)
        self.assertEqual(recurrence_score_multiplier(signal), 0.0)

    def test_saturated_family_is_penalized_after_cooldown(self):
        now = timezone.now()
        self._sent(now - timedelta(days=10))
        second = self._same_family_offer()
        self._sent(now - timedelta(days=8), offer=second)
        signal = recurrence_signal(self.offer, self.channel, now=now)
        self.assertFalse(signal.blocked)
        self.assertTrue(signal.penalized)
        self.assertEqual(recurrence_score_multiplier(signal), 0.72)

    def test_material_price_drop_remains_allowed_after_cooldown(self):
        old = self._sent(timezone.now() - timedelta(days=2))
        changed = Offer.objects.get(pk=self.offer.pk)
        changed.current_price = Decimal('780')
        changed.save(update_fields=['current_price', 'updated_at'])
        self.assertTrue(_should_republish_after_improvement(old, changed, 'Oferta R$ 780,00'))

    def test_failed_delivery_does_not_count_as_recurrence(self):
        Delivery.objects.create(
            offer=self.offer, social_channel=self.channel,
            message='Falhou', delivery_status=Delivery.DeliveryStatus.FAILED,
            sent_at=timezone.now() - timedelta(hours=1),
        )
        signal = recurrence_signal(self.offer, self.channel)
        self.assertEqual(signal.successful_sends, 0)
        self.assertFalse(signal.blocked)
