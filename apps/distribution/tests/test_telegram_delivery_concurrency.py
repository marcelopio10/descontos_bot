"""Testes de idempotência/concorrência do caminho de entrega do Telegram.

Cobre a Tarefa 3.2 do plano de refatoração (achado MÉDIO): antes desta
refatoração, `deliver_offer_to_telegram`/`deliver_curated_item_to_telegram`
decidiam se deviam enviar checando `Delivery.objects.filter(...).first()`
sem lock. Dois processos `publish_telegram` concorrentes podiam ambos ler
"ainda não enviado" ao mesmo tempo e disparar o envio real duas vezes.

Agora ambas as funções usam `_reserve_delivery_for_send` (mesmo helper do
caminho WhatsApp em `apps/distribution/services/delivery.py`), que reserva
a entrega (status `pending`) dentro de uma transação antes do envio externo.
"""
import threading
import time
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.telegram_client import TelegramSendResult
from apps.distribution.services.telegram_delivery import deliver_offer_to_telegram
from apps.distribution.services.telegram_rate_limiter import TelegramRateLimiter
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class FakeTelegramClient:
    """Client falso que conta chamadas reais de envio (thread-safe)."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.send_calls = 0
        self.status_calls = 0
        self._lock = threading.Lock()

    def send_photo(self, chat_id, photo_url, caption_html, inline_keyboard=None):
        with self._lock:
            self.send_calls += 1
        if self.delay:
            time.sleep(self.delay)
        return TelegramSendResult(
            success=True,
            message_id='tg-concurrent-1',
            sent_at=timezone.now(),
            error_message='',
        )

    def send_message(self, chat_id, text_html, inline_keyboard=None, disable_web_page_preview=True):
        with self._lock:
            self.send_calls += 1
        if self.delay:
            time.sleep(self.delay)
        return TelegramSendResult(
            success=True,
            message_id='tg-concurrent-1',
            sent_at=timezone.now(),
            error_message='',
        )


def _build_offer_and_channel():
    marketplace = Marketplace.objects.create(
        name='Amazon',
        code='amazon',
        base_url='https://amazon.example.com',
        is_active=True,
    )
    channel = SocialChannel.objects.create(
        name='Telegram Concorrência',
        code='telegram_concorrencia',
        channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
        target='-1009876543210',
        link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        is_enabled=True,
    )
    now = timezone.now()
    offer = Offer.objects.create(
        marketplace=marketplace,
        external_id='amz-concurrency-1',
        title='Fone de Ouvido Bluetooth com Cancelamento de Ruído',
        normalized_title='fone de ouvido bluetooth com cancelamento de ruido',
        offer_hash='hash-concurrency-1',
        slug='fone-bluetooth-concurrency-1',
        current_price=Decimal('199.90'),
        original_price=Decimal('399.80'),
        discount_pct=Decimal('50.00'),
        product_url='https://example.com/produto',
        affiliate_url='https://example.com/afiliado',
        image_url='https://example.com/original.jpg',
        is_active=True,
        first_seen_at=now,
        last_seen_at=now,
        price_collected_at=now,
    )
    return offer, channel


class TelegramDeliveryDeduplicationTests(TestCase):
    """Espelha `WhatsAppDeliveryDeduplicationTests` (apps/distribution/tests.py)
    para o caminho Telegram: simula a segunda chamada chegando depois que a
    primeira já reservou a entrega (status pending), mas antes de completar.
    """

    def setUp(self):
        self.offer, self.channel = _build_offer_and_channel()

    def test_recent_pending_delivery_blocks_duplicate_telegram_send(self):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='envio anterior em andamento',
            delivery_status=Delivery.DeliveryStatus.PENDING,
            error_message='Envio em andamento.',
        )
        client = FakeTelegramClient()

        with patch(
            'apps.distribution.services.telegram_delivery.is_distribution_silenced',
            return_value=False,
        ):
            result = deliver_offer_to_telegram(self.offer, self.channel, client=client)

        self.assertFalse(result.sent)
        self.assertEqual(client.send_calls, 0)
        self.assertEqual(result.delivery.delivery_status, Delivery.DeliveryStatus.PENDING)

    def test_sent_delivery_blocks_duplicate_telegram_send(self):
        Delivery.objects.create(
            offer=self.offer,
            social_channel=self.channel,
            message='mensagem já enviada',
            delivery_status=Delivery.DeliveryStatus.SENT,
            external_message_id='MSG-OLD',
            sent_at=timezone.now(),
        )
        client = FakeTelegramClient()

        with patch(
            'apps.distribution.services.telegram_delivery.is_distribution_silenced',
            return_value=False,
        ):
            result = deliver_offer_to_telegram(self.offer, self.channel, client=client)

        self.assertFalse(result.sent)
        self.assertEqual(client.send_calls, 0)
        self.assertEqual(result.delivery.external_message_id, 'MSG-OLD')


class TelegramDeliveryRealConcurrencyTests(TransactionTestCase):
    """Prova a correção de concorrência (Tarefa 3.2) com threads reais:
    dois processos `publish_telegram` concorrentes chamando
    `deliver_offer_to_telegram` para a MESMA oferta/canal ao mesmo tempo
    só podem resultar em 1 envio real ao Telegram.

    Usa `TransactionTestCase` (em vez de `TestCase`) porque cada thread abre
    sua própria conexão de banco; `TestCase` prende tudo numa única
    transação não commitada, invisível às outras conexões/threads.
    """

    def setUp(self):
        self.offer, self.channel = _build_offer_and_channel()

    def test_two_concurrent_deliver_offer_to_telegram_calls_send_only_once(self):
        client = FakeTelegramClient(delay=0.15)
        # Rate limiter dedicado (sem intervalo mínimo) para não confundir o
        # tempo de espera do limiter com o efeito da reserva sob teste.
        rate_limiter = TelegramRateLimiter(per_chat_seconds=0)
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                with patch(
                    'apps.distribution.services.telegram_delivery.is_distribution_silenced',
                    return_value=False,
                ):
                    result = deliver_offer_to_telegram(
                        self.offer,
                        self.channel,
                        client=client,
                        rate_limiter=rate_limiter,
                    )
                results.append(result)
            except Exception as exc:  # pragma: no cover - só para diagnosticar falha do teste
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors, f'threads levantaram exceções: {errors!r}')
        self.assertEqual(len(results), 2)

        # Só 1 mensagem real foi enviada ao Telegram, mesmo com 2 chamadas
        # concorrentes para a mesma oferta/canal.
        self.assertEqual(client.send_calls, 1)

        sent_flags = sorted(result.sent for result in results)
        self.assertEqual(sent_flags, [False, True])

        deliveries = Delivery.objects.filter(offer=self.offer, social_channel=self.channel)
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries.first().delivery_status, Delivery.DeliveryStatus.SENT)
