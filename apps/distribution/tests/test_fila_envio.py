from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services import fila_envio
from apps.distribution.services.telegram_client import TelegramSendResult
from apps.distribution.services.telegram_rate_limiter import TelegramRateLimiter
from apps.distribution.services.whatsapp_client import WhatsAppSendResult, WhatsAppStatus
from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class FakeWhatsAppClient:
    """Espelha `FakeWhatsAppClient` de `apps/distribution/tests.py`.

    `succeed_after` permite simular "falha N vezes, depois sucesso":
    None = sempre falha; 0 = sempre sucesso; k>0 = sucesso a partir da
    (k+1)-ésima chamada a `send_message`.
    """

    def __init__(self, connected=True, succeed_after=None):
        self.connected = connected
        self.succeed_after = succeed_after
        self.status_calls = 0
        self.send_calls = 0

    def get_status(self):
        self.status_calls += 1
        return WhatsAppStatus(connected=self.connected, jid='5511999999999@s.whatsapp.net')

    def send_message(self, destination, message, image_url=''):
        self.send_calls += 1
        success = self.succeed_after is not None and self.send_calls > self.succeed_after
        return WhatsAppSendResult(
            success=success,
            message_id='MSG-1' if success else '',
            sent_at=timezone.now() if success else None,
            error_message='' if success else 'falha simulada',
        )


class FakeTelegramClient:
    def __init__(self, succeed_after=None):
        self.succeed_after = succeed_after
        self.send_calls = 0

    def send_photo(self, chat_id, photo_url, caption_html, inline_keyboard=None):
        return self._result()

    def send_message(self, chat_id, text_html, inline_keyboard=None, disable_web_page_preview=True):
        return self._result()

    def _result(self):
        self.send_calls += 1
        success = self.succeed_after is not None and self.send_calls > self.succeed_after
        return TelegramSendResult(
            success=success,
            message_id='TG-1' if success else '',
            sent_at=timezone.now() if success else None,
            error_message='' if success else 'falha telegram simulada',
        )


def _fast_whatsapp_limiter():
    return WhatsAppRateLimiter(min_interval_seconds=0, max_sends_per_hour=0)


def _fast_telegram_limiter():
    return TelegramRateLimiter(per_chat_seconds=0)


class FilaEnvioTestCase(TestCase):
    """Base comum: marketplace/offer/canais usados em todos os testes da fila."""

    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='fila-envio-1',
            title='Fone Bluetooth XPTO',
            normalized_title='fone bluetooth xpto',
            offer_hash='fila-envio-1',
            slug='fone-bluetooth-xpto',
            current_price=Decimal('99.00'),
            original_price=Decimal('149.00'),
            discount_pct=Decimal('33.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )
        self.whatsapp_channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal_fila',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.telegram_channel = SocialChannel.objects.create(
            name='Telegram Principal',
            code='telegram_principal_fila',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='@descontosbot',
            link_strategy=SocialChannel.LinkStrategy.AFFILIATE_DIRECT,
        )


@patch('apps.distribution.services.fila_envio.enviar_alerta_operador')
@patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
@patch('apps.distribution.services.delivery.get_default_whatsapp_rate_limiter', side_effect=_fast_whatsapp_limiter)
@patch('apps.distribution.services.delivery.WhatsAppClient')
class RetryBackoffDeadLetterTests(FilaEnvioTestCase):
    """Cobre o item 1 da verificação: retry incrementa, backoff cresce,
    dead-letter após MAX_RETRIES e nenhum loop infinito depois disso.

    IMPORTANTE: `enviar_alerta_operador` é sempre mockado aqui — sem o mock,
    o dead-letter dispara um alerta real via Telegram para o operador
    (`apps.analytics.services.alertas`, que usa credenciais reais do `.env`
    quando configuradas). Isso foi descoberto da forma mais dura possível
    durante o desenvolvimento deste teste: uma primeira execução sem o mock
    chegou a enviar um alerta de verdade para o chat do operador com dados
    fictícios de teste.
    """

    def setUp(self):
        super().setUp()
        self.delivery = Delivery.objects.create(
            offer=self.offer,
            social_channel=self.whatsapp_channel,
            message='mensagem original',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='falha original simulada',
        )

    def test_retries_then_dead_letters_without_further_loop(
        self, mock_client_cls, _mock_limiter, _silenced, mock_alerta,
    ):
        fake_client = FakeWhatsAppClient(connected=True, succeed_after=None)  # sempre falha
        mock_client_cls.return_value = fake_client

        max_retries = fila_envio.get_max_retries()
        self.assertEqual(max_retries, 5)

        previous_next_retry_at = None
        for attempt in range(1, max_retries + 1):
            before_call = timezone.now()
            summary = fila_envio.process_queue()
            self.delivery.refresh_from_db()

            self.assertEqual(len(summary.outcomes), 1, f'tentativa {attempt}')

            if attempt < max_retries:
                self.assertEqual(summary.retry_scheduled, 1, f'tentativa {attempt}')
                self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.FAILED)
                self.assertEqual(self.delivery.retry_count, attempt)
                self.assertIsNotNone(self.delivery.next_retry_at)

                expected_delay_minutes = min(2 ** attempt, fila_envio.BACKOFF_CAP_MINUTES)
                actual_delay = self.delivery.next_retry_at - before_call
                self.assertAlmostEqual(
                    actual_delay.total_seconds() / 60,
                    expected_delay_minutes,
                    delta=0.2,
                    msg=f'backoff incorreto na tentativa {attempt}',
                )

                if previous_next_retry_at is not None:
                    self.assertGreater(
                        self.delivery.next_retry_at, previous_next_retry_at,
                        f'next_retry_at deveria crescer na tentativa {attempt}',
                    )
                previous_next_retry_at = self.delivery.next_retry_at

                # Simula o tempo de backoff já ter passado, para que o item
                # volte a ser elegível na próxima chamada de process_queue().
                self.delivery.next_retry_at = timezone.now() - timedelta(seconds=1)
                self.delivery.save(update_fields=['next_retry_at'])
            else:
                self.assertEqual(summary.dead_lettered, 1)
                self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.DEAD_LETTER)
                self.assertEqual(self.delivery.retry_count, max_retries)
                self.assertIsNone(self.delivery.next_retry_at)
                # `error_message` reflete a razão da ÚLTIMA tentativa (cada
                # chamada a `deliver_offer_to_channel` sobrescreve o campo com
                # o erro mais recente) — o dead-letter preserva essa razão em
                # vez de substituí-la por um texto genérico.
                self.assertIn('falha simulada', self.delivery.error_message)
                self.assertIn('dead-letter', self.delivery.error_message)
                mock_alerta.assert_called_once()
                self.assertEqual(mock_alerta.call_args.kwargs.get('categoria'), 'fila_envio_dead_letter')

        # Rodar mais uma vez após o dead-letter: nada deve acontecer.
        calls_before = fake_client.send_calls
        summary_after = fila_envio.process_queue()
        self.delivery.refresh_from_db()

        self.assertEqual(len(summary_after.outcomes), 0, 'não deve haver mais candidatos elegíveis')
        self.assertEqual(fake_client.send_calls, calls_before, 'não deve tentar enviar de novo')
        self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.DEAD_LETTER)
        self.assertEqual(self.delivery.retry_count, max_retries)


@patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
@patch('apps.distribution.services.delivery.get_default_whatsapp_rate_limiter', side_effect=_fast_whatsapp_limiter)
@patch('apps.distribution.services.delivery.WhatsAppClient')
class SuccessClearsRetryTests(FilaEnvioTestCase):
    """Cobre o item 2 da verificação: sucesso no reenvio marca SENT e some da fila."""

    def setUp(self):
        super().setUp()
        self.delivery = Delivery.objects.create(
            offer=self.offer,
            social_channel=self.whatsapp_channel,
            message='mensagem original',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='falha anterior',
            retry_count=2,
            next_retry_at=timezone.now() - timedelta(minutes=1),
        )

    def test_success_marks_sent_and_is_no_longer_eligible(self, mock_client_cls, _mock_limiter, _silenced):
        fake_client = FakeWhatsAppClient(connected=True, succeed_after=0)  # sucesso na próxima tentativa
        mock_client_cls.return_value = fake_client

        summary = fila_envio.process_queue()

        self.assertEqual(summary.sent, 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.SENT)
        self.assertIsNotNone(self.delivery.sent_at)
        self.assertIsNone(self.delivery.next_retry_at)
        self.assertEqual(self.delivery.retry_count, 2, 'retry_count é histórico; sucesso não precisa zerar')

        # Uma segunda chamada não deve nem tentar: já não é FAILED.
        summary_2 = fila_envio.process_queue()
        self.assertEqual(len(summary_2.outcomes), 0)
        self.assertEqual(fake_client.send_calls, 1)


@patch('apps.distribution.services.telegram_delivery.is_distribution_silenced', return_value=False)
@patch('apps.distribution.services.telegram_delivery.get_default_limiter', side_effect=_fast_telegram_limiter)
@patch('apps.distribution.services.telegram_delivery.TelegramClient')
class TelegramRoutingTests(FilaEnvioTestCase):
    """Confirma que Deliveries de canal Telegram são roteadas para o caminho
    Telegram (e não WhatsApp), usando `channel_type` do `SocialChannel`."""

    def setUp(self):
        super().setUp()
        self.delivery = Delivery.objects.create(
            offer=self.offer,
            social_channel=self.telegram_channel,
            message='mensagem original',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='falha anterior telegram',
        )

    def test_telegram_delivery_routed_to_telegram_path(self, mock_client_cls, _mock_limiter, _silenced):
        fake_client = FakeTelegramClient(succeed_after=0)
        mock_client_cls.return_value = fake_client

        with patch('apps.distribution.services.delivery.WhatsAppClient') as mock_wa_cls:
            summary = fila_envio.process_queue()
            mock_wa_cls.assert_not_called()

        self.assertEqual(summary.sent, 1)
        self.assertEqual(fake_client.send_calls, 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.SENT)


class WhatsAppSessionDownPrecheckTests(FilaEnvioTestCase):
    """A sessão do WhatsApp indisponível não deve consumir tentativa/backoff."""

    def setUp(self):
        super().setUp()
        self.delivery = Delivery.objects.create(
            offer=self.offer,
            social_channel=self.whatsapp_channel,
            message='mensagem original',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='falha anterior',
        )

    @patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False)
    @patch('apps.distribution.services.delivery.WhatsAppClient')
    def test_session_down_skips_without_consuming_retry_budget(self, mock_client_cls, _silenced):
        fake_client = FakeWhatsAppClient(connected=False)
        mock_client_cls.return_value = fake_client

        summary = fila_envio.process_queue()

        self.assertEqual(len(summary.outcomes), 1)
        self.assertEqual(summary.outcomes[0].status, fila_envio.OUTCOME_SKIPPED_SESSION_DOWN)
        self.assertEqual(fake_client.send_calls, 0, 'não deve nem tentar enviar')

        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.FAILED)
        self.assertEqual(self.delivery.retry_count, 0)
        self.assertIsNone(self.delivery.next_retry_at)


class EligibilityQueryTests(FilaEnvioTestCase):
    """`get_eligible_deliveries` só deve trazer FAILED, dentro do teto de
    tentativas e fora (ou sem) janela de backoff."""

    def test_filters_out_sent_dead_letter_future_backoff_and_exhausted(self):
        now = timezone.now()

        eligible_no_backoff = Delivery.objects.create(
            offer=self.offer, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.FAILED,
        )

        offer_2 = Offer.objects.create(
            marketplace=self.marketplace, external_id='fila-envio-2',
            title='Produto 2', normalized_title='produto 2', offer_hash='fila-envio-2',
            slug='produto-2', current_price=Decimal('10'), original_price=Decimal('20'),
            discount_pct=Decimal('50'), product_url='https://example.com/p2',
            affiliate_url='https://example.com/a2', image_url='https://example.com/i2.jpg',
            is_active=True, first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )
        eligible_backoff_elapsed = Delivery.objects.create(
            offer=offer_2, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.FAILED,
            next_retry_at=now - timedelta(minutes=1),
        )

        offer_3 = Offer.objects.create(
            marketplace=self.marketplace, external_id='fila-envio-3',
            title='Produto 3', normalized_title='produto 3', offer_hash='fila-envio-3',
            slug='produto-3', current_price=Decimal('10'), original_price=Decimal('20'),
            discount_pct=Decimal('50'), product_url='https://example.com/p3',
            affiliate_url='https://example.com/a3', image_url='https://example.com/i3.jpg',
            is_active=True, first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )
        Delivery.objects.create(
            offer=offer_3, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.FAILED,
            next_retry_at=now + timedelta(minutes=30),
        )  # ainda em backoff -> não elegível

        offer_4 = Offer.objects.create(
            marketplace=self.marketplace, external_id='fila-envio-4',
            title='Produto 4', normalized_title='produto 4', offer_hash='fila-envio-4',
            slug='produto-4', current_price=Decimal('10'), original_price=Decimal('20'),
            discount_pct=Decimal('50'), product_url='https://example.com/p4',
            affiliate_url='https://example.com/a4', image_url='https://example.com/i4.jpg',
            is_active=True, first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )
        Delivery.objects.create(
            offer=offer_4, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=now,
        )  # já enviado -> nunca elegível

        offer_5 = Offer.objects.create(
            marketplace=self.marketplace, external_id='fila-envio-5',
            title='Produto 5', normalized_title='produto 5', offer_hash='fila-envio-5',
            slug='produto-5', current_price=Decimal('10'), original_price=Decimal('20'),
            discount_pct=Decimal('50'), product_url='https://example.com/p5',
            affiliate_url='https://example.com/a5', image_url='https://example.com/i5.jpg',
            is_active=True, first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )
        Delivery.objects.create(
            offer=offer_5, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.DEAD_LETTER,
            retry_count=5,
        )  # esgotado -> não elegível

        offer_6 = Offer.objects.create(
            marketplace=self.marketplace, external_id='fila-envio-6',
            title='Produto 6', normalized_title='produto 6', offer_hash='fila-envio-6',
            slug='produto-6', current_price=Decimal('10'), original_price=Decimal('20'),
            discount_pct=Decimal('50'), product_url='https://example.com/p6',
            affiliate_url='https://example.com/a6', image_url='https://example.com/i6.jpg',
            is_active=True, first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )
        Delivery.objects.create(
            offer=offer_6, social_channel=self.whatsapp_channel,
            message='m', delivery_status=Delivery.DeliveryStatus.FAILED,
            retry_count=5,
        )  # FAILED mas já no teto de tentativas -> não elegível

        eligible = fila_envio.get_eligible_deliveries()
        eligible_ids = {delivery.id for delivery in eligible}

        self.assertEqual(eligible_ids, {eligible_no_backoff.id, eligible_backoff_elapsed.id})


class DryRunTests(FilaEnvioTestCase):
    """`dry_run=True` não deve chamar nenhum client nem alterar o banco."""

    def setUp(self):
        super().setUp()
        self.delivery = Delivery.objects.create(
            offer=self.offer,
            social_channel=self.whatsapp_channel,
            message='mensagem original',
            delivery_status=Delivery.DeliveryStatus.FAILED,
            error_message='falha anterior',
        )

    @patch('apps.distribution.services.delivery.WhatsAppClient')
    def test_dry_run_does_not_call_client_or_mutate_state(self, mock_client_cls):
        summary = fila_envio.process_queue(dry_run=True)

        self.assertEqual(len(summary.outcomes), 1)
        self.assertEqual(summary.would_retry, 1)
        mock_client_cls.assert_not_called()

        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.delivery_status, Delivery.DeliveryStatus.FAILED)
        self.assertEqual(self.delivery.retry_count, 0)
        self.assertIsNone(self.delivery.next_retry_at)
