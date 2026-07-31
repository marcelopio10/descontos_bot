from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.telegram_client import TelegramSendResult
from apps.distribution.services.whatsapp_client import WhatsAppSendResult, WhatsAppStatus
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting


class FakeWhatsAppClient:
    def __init__(self):
        self.sent = []

    def get_status(self):
        return WhatsAppStatus(connected=True, jid='bot@example.net')

    def send_message(self, destination, message, image_url=''):
        self.sent.append((destination, message, image_url))
        return WhatsAppSendResult(True, f'wa-prod-{len(self.sent)}', timezone.now(), '')


class FakeTelegramClient:
    def __init__(self):
        self.sent = []

    def send_photo(self, chat_id, photo_url, caption_html, inline_keyboard):
        self.sent.append((chat_id, caption_html, photo_url))
        return TelegramSendResult(True, f'tg-prod-{len(self.sent)}', timezone.now(), '')

    def send_message(self, chat_id, text_html, inline_keyboard, disable_web_page_preview=True):
        self.sent.append((chat_id, text_html, ''))
        return TelegramSendResult(True, f'tg-prod-{len(self.sent)}', timezone.now(), '')


class AICuratedProductionAssistTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://amazon.example.com',
            is_active=True,
        )
        now = timezone.now()
        self.offers = []
        for index in range(3):
            self.offers.append(Offer.objects.create(
                marketplace=self.marketplace,
                external_id=f'prod-ai-{index}',
                title=f'Oferta produção assistida {index}',
                normalized_title=f'oferta producao assistida {index}',
                offer_hash=f'prod-ai-{index}',
                slug=f'prod-ai-{index}',
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
            ))

    def _channel(self, code, channel_type, target):
        return SocialChannel.objects.create(
            name=code.replace('_', ' ').title(),
            code=code,
            channel_type=channel_type,
            target=target,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )

    def _ready_batch(self, channel):
        run = CurationRun.objects.create(
            channel=channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.PRODUCTION,
            profile_name='descontos-bot',
            model_provider='openai-codex',
            model_name='gpt-5.5',
            candidate_count=len(self.offers),
            selected_count=len(self.offers),
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=channel,
            status=CuratedBatch.Status.READY,
            batch_size=len(self.offers),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        for position, offer in enumerate(self.offers, start=1):
            decision = CurationDecision.objects.create(
                run=run,
                offer=offer,
                marketplace_code='amazon',
                ai_score=Decimal('95'),
                ai_classification=CurationDecision.Classification.APPROVED,
                decision_reason='Oferta aprovada para produção assistida.',
                title_original=offer.title,
                title_rewritten=f'Título produção {position}',
                caption_rewritten=f'Caption produção {position}',
                raw_ai_json={},
                is_selected_for_batch=True,
            )
            CuratedBatchItem.objects.create(
                batch=batch,
                decision=decision,
                offer=offer,
                position=position,
                final_title=f'Título produção {position}',
                final_caption_whatsapp=f'Caption WhatsApp produção {position}',
                final_caption_telegram=f'Caption Telegram produção {position}',
                final_image_url='https://example.com/final.jpg',
            )
        return batch

    @override_settings(ALLOW_PRODUCTION_WHATSAPP_SEND=True)
    def test_whatsapp_production_ai_requires_explicit_confirmation(self):
        self._channel('whatsapp_principal', SocialChannel.ChannelType.WHATSAPP_GROUP, 'descontos.bot')

        with self.assertRaises(CommandError) as exc:
            call_command(
                'run_bot',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_principal',
                '--ai-curation',
                '--ai-curation-required',
            )

        self.assertIn('confirm-ai-production', str(exc.exception))
        self.assertEqual(Delivery.objects.count(), 0)

    @override_settings(ALLOW_PRODUCTION_WHATSAPP_SEND=True)
    def test_whatsapp_production_ai_confirmed_sends_only_limited_curated_items(self):
        channel = self._channel('whatsapp_principal', SocialChannel.ChannelType.WHATSAPP_GROUP, 'descontos.bot')
        batch = self._ready_batch(channel)
        fake_client = FakeWhatsAppClient()
        # `usa_fila_desacoplada` é True por padrão desde 2026-07-21: este teste cobre
        # o envio assistido SÍNCRONO (mesmo comando), então desliga explicitamente —
        # o fluxo desacoplado real usa `consumir_fila_whatsapp` em processo separado.
        Setting.objects.create(key='usa_fila_desacoplada', value='false')

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
                'whatsapp_principal',
                '--ai-curation',
                '--ai-curation-required',
                '--confirm-ai-production',
                'CONFIRM_AI_PRODUCTION',
                '--ai-curation-limit',
                '1',
                stdout=out,
            )

        batch.refresh_from_db()
        statuses = list(batch.items.order_by('position').values_list('send_status', flat=True))
        self.assertEqual(len(fake_client.sent), 1)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(statuses, ['sent', 'pending', 'pending'])
        self.assertEqual(batch.status, CuratedBatch.Status.READY)
        self.assertIn('Enviadas 1/1', out.getvalue())

    @override_settings(ALLOW_PRODUCTION_WHATSAPP_SEND=True)
    def test_whatsapp_production_ai_required_without_batch_pauses_without_selector_fallback(self):
        self._channel('whatsapp_principal', SocialChannel.ChannelType.WHATSAPP_GROUP, 'descontos.bot')
        out = StringIO()

        call_command(
            'run_bot',
            '--once',
            '--skip-scraping',
            '--channel',
            'whatsapp_principal',
            '--ai-curation-required',
            '--confirm-ai-production',
            'CONFIRM_AI_PRODUCTION',
            stdout=out,
        )

        self.assertIn('Nenhum lote curado pronto', out.getvalue())
        self.assertNotIn('Ofertas selecionadas', out.getvalue())
        self.assertEqual(Delivery.objects.count(), 0)

    @override_settings(ALLOW_PRODUCTION_TELEGRAM_SEND=True)
    def test_telegram_production_ai_confirmed_sends_only_limited_curated_items(self):
        channel = self._channel('telegram_main', SocialChannel.ChannelType.TELEGRAM_CHANNEL, '-100999')
        batch = self._ready_batch(channel)
        fake_client = FakeTelegramClient()

        with (
            patch('apps.distribution.services.telegram_delivery.TelegramClient', return_value=fake_client),
            patch('apps.distribution.services.telegram_delivery.is_distribution_silenced', return_value=False),
            patch('apps.distribution.management.commands.publish_telegram.is_distribution_silenced', return_value=False),
        ):
            out = StringIO()
            call_command(
                'publish_telegram',
                '--once',
                '--channel',
                'telegram_main',
                '--ai-curation',
                '--ai-curation-required',
                '--confirm-ai-production',
                'CONFIRM_AI_PRODUCTION',
                '--limit',
                '1',
                stdout=out,
            )

        batch.refresh_from_db()
        statuses = list(batch.items.order_by('position').values_list('send_status', flat=True))
        self.assertEqual(len(fake_client.sent), 1)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(statuses, ['sent', 'pending', 'pending'])
        self.assertEqual(batch.status, CuratedBatch.Status.READY)
        self.assertIn('Enviadas 1/1', out.getvalue())
