from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.delivery import deliver_offer_to_channel
from apps.distribution.services.whatsapp_client import WhatsAppClient, WhatsAppSendResult, WhatsAppStatus
from apps.market_intel.services.whatsapp_observer_client import WhatsAppObserverClient
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class FakeWhatsAppClient:
    def __init__(self, *, connected=True, success=True):
        self.connected = connected
        self.success = success
        self.status_calls = 0
        self.send_calls = 0

    def get_status(self):
        self.status_calls += 1
        return WhatsAppStatus(connected=self.connected, jid='5511999999999@s.whatsapp.net')

    def send_message(self, destination, message, image_url=''):
        self.send_calls += 1
        return WhatsAppSendResult(
            success=self.success,
            message_id='MSG-1' if self.success else '',
            sent_at=timezone.now() if self.success else None,
            error_message='' if self.success else 'falha simulada',
        )


class WhatsAppProviderRoutingTests(SimpleTestCase):
    @override_settings(
        WA_PROVIDER='baileys',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_default_baileys_provider_uses_wa_service_url(self):
        self.assertEqual(WhatsAppClient().base_url, 'http://127.0.0.1:8787')
        self.assertEqual(WhatsAppObserverClient().base_url, 'http://127.0.0.1:8787')

    @override_settings(
        WA_PROVIDER='evolution',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_evolution_provider_uses_evolution_adapter_url_for_send_and_observer(self):
        self.assertEqual(WhatsAppClient().base_url, 'http://127.0.0.1:8788')
        self.assertEqual(WhatsAppObserverClient().base_url, 'http://127.0.0.1:8788')

    @override_settings(WA_PROVIDER='evolution', EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788')
    def test_explicit_base_url_overrides_provider_routing(self):
        self.assertEqual(WhatsAppClient(base_url='http://custom.local').base_url, 'http://custom.local')
        self.assertEqual(WhatsAppObserverClient(base_url='http://custom.local').base_url, 'http://custom.local')


class WhatsAppDeliveryDeduplicationTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Shopee',
            code='shopee',
            base_url='https://shopee.com.br',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='item:shop',
            title='Cafeteira Elétrica Inox 30 Xícaras Oferta Especial',
            normalized_title='cafeteira eletrica inox 30 xicaras oferta especial',
            offer_hash='hash-cafeteira',
            slug='cafeteira-eletrica-inox',
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=Decimal('46.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    @patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
    def test_successful_send_creates_pending_reservation_then_marks_sent(self, _silenced):
        client = FakeWhatsAppClient()

        result = deliver_offer_to_channel(self.offer, self.channel, client=client)

        self.assertTrue(result.sent)
        self.assertEqual(client.send_calls, 1)
        result.delivery.refresh_from_db()
        self.assertEqual(result.delivery.delivery_status, Delivery.DeliveryStatus.SENT)
        self.assertEqual(result.delivery.external_message_id, 'MSG-1')

    @patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
    def test_recent_pending_delivery_blocks_duplicate_same_channel_send(self, _silenced):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='envio anterior em andamento',
            delivery_status=Delivery.DeliveryStatus.PENDING,
            error_message='Envio em andamento.',
        )
        client = FakeWhatsAppClient()

        result = deliver_offer_to_channel(self.offer, self.channel, client=client)

        self.assertFalse(result.sent)
        self.assertEqual(client.status_calls, 0)
        self.assertEqual(client.send_calls, 0)
        self.assertEqual(result.delivery.delivery_status, Delivery.DeliveryStatus.PENDING)

    @patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
    def test_sent_delivery_blocks_duplicate_same_channel_send(self, _silenced):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='mensagem enviada',
            delivery_status=Delivery.DeliveryStatus.SENT,
            external_message_id='MSG-OLD',
            sent_at=timezone.now(),
        )
        client = FakeWhatsAppClient()

        result = deliver_offer_to_channel(self.offer, self.channel, client=client)

        self.assertFalse(result.sent)
        self.assertEqual(client.status_calls, 0)
        self.assertEqual(client.send_calls, 0)
        self.assertEqual(result.delivery.external_message_id, 'MSG-OLD')

    @patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
    def test_sent_delivery_can_reenter_after_material_price_improvement(self, _silenced):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='Oferta anterior por R$ 100,00',
            delivery_status=Delivery.DeliveryStatus.SENT,
            external_message_id='MSG-OLD',
            sent_at=timezone.now() - timezone.timedelta(days=2),
        )
        client = FakeWhatsAppClient()

        result = deliver_offer_to_channel(self.offer, self.channel, client=client)

        self.assertTrue(result.sent)
        self.assertEqual(client.send_calls, 1)
        self.assertNotEqual(result.delivery.external_message_id, 'MSG-OLD')
