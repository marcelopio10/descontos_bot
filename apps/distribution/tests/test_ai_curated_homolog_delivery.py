from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.telegram_client import TelegramSendResult
from apps.distribution.services.whatsapp_client import WhatsAppSendResult, WhatsAppStatus
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class FakeWhatsAppClient:
    def get_status(self):
        return WhatsAppStatus(connected=True, jid='bot@example.net')

    def send_message(self, destination, message, image_url=''):
        self.destination = destination
        self.message = message
        self.image_url = image_url
        return WhatsAppSendResult(
            success=True,
            message_id='wa-curated-1',
            sent_at=timezone.now(),
            error_message='',
        )


class FakeTelegramClient:
    def send_photo(self, chat_id, photo_url, caption_html, inline_keyboard):
        self.chat_id = chat_id
        self.photo_url = photo_url
        self.caption_html = caption_html
        self.inline_keyboard = inline_keyboard
        return TelegramSendResult(
            success=True,
            message_id='tg-curated-1',
            sent_at=timezone.now(),
            error_message='',
        )

    def send_message(self, chat_id, text_html, inline_keyboard, disable_web_page_preview=True):
        self.chat_id = chat_id
        self.text_html = text_html
        self.inline_keyboard = inline_keyboard
        return TelegramSendResult(
            success=True,
            message_id='tg-curated-1',
            sent_at=timezone.now(),
            error_message='',
        )


class AICuratedHomologDeliveryTests(TestCase):
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
            external_id='s12-offer-1',
            title='Título original não curado',
            normalized_title='titulo original nao curado',
            offer_hash='s12-offer-1',
            slug='s12-offer-1',
            current_price=Decimal('89.90'),
            original_price=Decimal('179.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/original.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def _channel(self, code, channel_type, target):
        return SocialChannel.objects.create(
            name=code.replace('_', ' ').title(),
            code=code,
            channel_type=channel_type,
            target=target,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )

    def _ready_batch_item(self, channel):
        run = CurationRun.objects.create(
            channel=channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.HOMOLOG,
            profile_name='descontos-bot',
            model_provider='openai-codex',
            model_name='gpt-5.5',
            candidate_count=1,
            selected_count=1,
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=self.offer,
            marketplace_code='amazon',
            ai_score=Decimal('95'),
            ai_classification=CurationDecision.Classification.APPROVED,
            decision_reason='Oferta boa para homologação.',
            title_original=self.offer.title,
            title_rewritten='Título curado Sprint 12',
            caption_rewritten='Caption curada Sprint 12',
            raw_ai_json={},
            is_selected_for_batch=True,
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        item = CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=self.offer,
            position=1,
            final_title='Título curado Sprint 12',
            final_caption_whatsapp='Caption WhatsApp curada Sprint 12',
            final_caption_telegram='Caption Telegram <b>curada</b> Sprint 12',
            final_image_url='https://example.com/final.jpg',
        )
        return batch, item

    def test_whatsapp_ai_curation_real_homolog_sends_curated_caption_and_marks_audit(self):
        channel = self._channel('whatsapp_main', SocialChannel.ChannelType.WHATSAPP_GROUP, 'descontos.bot homolog')
        batch, item = self._ready_batch_item(channel)
        fake_client = FakeWhatsAppClient()

        with (
            patch('apps.distribution.services.delivery.WhatsAppClient', return_value=fake_client),
            patch('apps.distribution.services.delivery.is_distribution_silenced', return_value=False),
        ):
            out = StringIO()
            call_command(
                'run_bot',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                '--ai-curation',
                stdout=out,
            )

        item.refresh_from_db()
        batch.refresh_from_db()
        delivery = Delivery.objects.get(offer=self.offer, social_channel=channel)
        self.assertEqual(fake_client.destination, 'descontos.bot homolog')
        self.assertIn('Caption WhatsApp curada Sprint 12', fake_client.message)
        self.assertEqual(fake_client.image_url, 'https://example.com/final.jpg')
        self.assertEqual(delivery.delivery_status, Delivery.DeliveryStatus.SENT)
        self.assertIn('Caption WhatsApp curada Sprint 12', delivery.message)
        self.assertIn('🛒 Compre aqui 👇', delivery.message)
        self.assertIn('https://descontos-bot.vercel.app/r?', delivery.message)
        self.assertIn('🤖 @descontos.bot', delivery.message)
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.SENT)
        self.assertEqual(item.delivery, delivery)
        self.assertEqual(batch.status, CuratedBatch.Status.SENT)
        self.assertIn('Enviadas 1/1', out.getvalue())

    def test_telegram_ai_curation_real_homolog_sends_curated_payload_and_marks_audit(self):
        channel = self._channel('telegram_homolog', SocialChannel.ChannelType.TELEGRAM_CHANNEL, '-1001234567890')
        batch, item = self._ready_batch_item(channel)
        fake_client = FakeTelegramClient()

        with (
            patch('apps.distribution.services.telegram_delivery.TelegramClient', return_value=fake_client),
            patch('apps.distribution.services.telegram_delivery.is_distribution_silenced', return_value=False),
        ):
            out = StringIO()
            call_command(
                'publish_telegram',
                '--once',
                '--channel',
                'telegram_homolog',
                '--ai-curation',
                stdout=out,
            )

        item.refresh_from_db()
        batch.refresh_from_db()
        delivery = Delivery.objects.get(offer=self.offer, social_channel=channel)
        self.assertEqual(fake_client.chat_id, '-1001234567890')
        self.assertEqual(fake_client.photo_url, 'https://example.com/final.jpg')
        self.assertIn('Caption Telegram &lt;b&gt;curada&lt;/b&gt; Sprint 12', fake_client.caption_html)
        self.assertEqual(delivery.delivery_status, Delivery.DeliveryStatus.SENT)
        self.assertEqual(delivery.message, fake_client.caption_html)
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.SENT)
        self.assertEqual(item.delivery, delivery)
        self.assertEqual(batch.status, CuratedBatch.Status.SENT)
        self.assertIn('Enviadas 1/1', out.getvalue())
