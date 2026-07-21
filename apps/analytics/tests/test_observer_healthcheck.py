from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.analytics.services.observer_healthcheck import (
    canais_sem_entrega_recente,
    observer_esta_atrasado,
    verificar_canais_sem_entrega,
    verificar_observer_atrasado,
)
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.offers.models import Offer


class ObserverAtrasadoTests(TestCase):
    def setUp(self):
        self.group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas Teste',
            jid='123@g.us',
        )

    def _create_message(self, collected_at, external_id='msg-1'):
        now = timezone.now()
        return ObservedWhatsAppMessage.objects.create(
            group=self.group,
            external_message_id=external_id,
            sender_hash='hash-1',
            sent_at=now,
            collected_at=collected_at,
            text='oferta teste',
        )

    def test_observer_esta_atrasado_true_when_no_messages_ever_collected(self):
        self.assertTrue(observer_esta_atrasado(horas_limite=24))

    def test_observer_esta_atrasado_false_when_recent_message_collected(self):
        self._create_message(timezone.now() - timezone.timedelta(hours=1))
        self.assertFalse(observer_esta_atrasado(horas_limite=24))

    def test_observer_esta_atrasado_true_when_last_message_older_than_limit(self):
        self._create_message(timezone.now() - timezone.timedelta(hours=30))
        self.assertTrue(observer_esta_atrasado(horas_limite=24))

    @patch('apps.analytics.services.observer_healthcheck.alertar_observer_atrasado')
    def test_verificar_observer_atrasado_fires_alert_only_when_stale(self, mock_alert):
        # Sem histórico: deve alertar.
        self.assertTrue(verificar_observer_atrasado(horas_limite=24))
        mock_alert.assert_called_once_with(24)

        mock_alert.reset_mock()
        self._create_message(timezone.now() - timezone.timedelta(hours=1))
        self.assertFalse(verificar_observer_atrasado(horas_limite=24))
        mock_alert.assert_not_called()


class CanaisSemEntregaTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://amazon.example.com',
            is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='offer-1',
            title='Produto teste',
            normalized_title='produto teste',
            offer_hash='hash-observer-healthcheck-1',
            slug='produto-teste-observer-healthcheck',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )
        self.channel = SocialChannel.objects.create(
            name='Telegram Main',
            code='telegram_main',
            target='@canal',
            is_enabled=True,
        )

    def test_channel_with_no_delivery_at_all_is_flagged(self):
        self.assertEqual(canais_sem_entrega_recente(horas_limite=24), ['telegram_main'])

    def test_channel_with_recent_sent_delivery_is_not_flagged(self):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=timezone.now() - timezone.timedelta(hours=2),
        )
        self.assertEqual(canais_sem_entrega_recente(horas_limite=24), [])

    def test_channel_with_only_old_sent_delivery_is_flagged(self):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=timezone.now() - timezone.timedelta(hours=48),
        )
        self.assertEqual(canais_sem_entrega_recente(horas_limite=24), ['telegram_main'])

    def test_channel_with_only_failed_delivery_is_still_flagged(self):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='deu ruim',
        )
        self.assertEqual(canais_sem_entrega_recente(horas_limite=24), ['telegram_main'])

    def test_disabled_channel_is_ignored(self):
        self.channel.is_enabled = False
        self.channel.save(update_fields=['is_enabled'])
        self.assertEqual(canais_sem_entrega_recente(horas_limite=24), [])

    @patch('apps.analytics.services.observer_healthcheck.alertar_canal_sem_entrega')
    def test_verificar_canais_sem_entrega_fires_alert_per_channel(self, mock_alert):
        alertados = verificar_canais_sem_entrega(horas_limite=24)
        self.assertEqual(alertados, ['telegram_main'])
        mock_alert.assert_called_once_with('telegram_main', 24)
