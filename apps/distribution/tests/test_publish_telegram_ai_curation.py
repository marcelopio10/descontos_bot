from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.telegram_message_builder import CAPTION_MAX, build_curated_telegram_payload
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class PublishTelegramAICurationTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='Telegram Homolog',
            code='telegram_homolog',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='-1001234567890',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://amazon.example.com',
            is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='amz-s11-1',
            title='Título selector antigo Telegram',
            normalized_title='titulo selector antigo telegram',
            offer_hash='hash-s11-1',
            slug='titulo-selector-antigo-telegram',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/original.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def _create_ready_batch(self, *, caption='Caption <b>curada</b> Telegram', local_image_path=''):
        run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.DRY_RUN,
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
            ai_score=Decimal('90'),
            ai_classification=CurationDecision.Classification.APPROVED,
            conversion_score=Decimal('90'),
            relevance_score=Decimal('90'),
            discount_quality_score=Decimal('90'),
            audience_fit_score=Decimal('90'),
            decision_reason='Boa oferta curada.',
            title_original=self.offer.title,
            title_rewritten='Título curado Telegram',
            caption_rewritten=caption,
            raw_ai_json={},
            is_selected_for_batch=True,
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=self.channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        item = CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=self.offer,
            position=1,
            final_title='Título curado Telegram',
            final_caption_whatsapp=caption,
            final_caption_telegram=caption,
            final_image_url='https://example.com/final.jpg',
            local_image_path=local_image_path,
        )
        return batch, item

    def test_dry_run_ai_curation_prints_ready_batch_with_curated_caption_and_image_without_delivery(self):
        batch, _item = self._create_ready_batch(local_image_path='media/curation/local-final.jpg')
        out = StringIO()

        call_command(
            'publish_telegram',
            '--once',
            '--channel',
            'telegram_homolog',
            '--ai-curation',
            '--dry-run',
            stdout=out,
        )

        text = out.getvalue()
        self.assertIn(f'Lote curado #{batch.id}', text)
        self.assertIn('Título curado Telegram', text)
        self.assertIn('Caption &lt;b&gt;curada&lt;/b&gt;', text)
        self.assertIn('photo_url=media/curation/local-final.jpg', text)
        self.assertIn('dry_run ativo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_ai_curation_without_ready_batch_pauses_without_selector_fallback(self):
        out = StringIO()

        call_command(
            'publish_telegram',
            '--once',
            '--channel',
            'telegram_homolog',
            '--ai-curation',
            '--dry-run',
            stdout=out,
        )

        text = out.getvalue()
        self.assertIn('Nenhum lote curado pronto', text)
        self.assertNotIn('Título selector antigo Telegram', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_ai_curated_caption_is_truncated_to_telegram_caption_limit(self):
        self._create_ready_batch(caption='x' * (CAPTION_MAX + 200))
        out = StringIO()

        call_command(
            'publish_telegram',
            '--once',
            '--channel',
            'telegram_homolog',
            '--ai-curation',
            '--dry-run',
            stdout=out,
        )

        marker = 'caption:\n'
        caption = out.getvalue().split(marker, 1)[1].split('\ndry_run ativo', 1)[0].strip()
        self.assertLessEqual(len(caption), CAPTION_MAX)
        self.assertTrue(caption.endswith('…'))
        self.assertEqual(Delivery.objects.count(), 0)

    def test_curated_telegram_caption_uses_structured_template_and_non_repetitive_agent_highlight(self):
        self.offer.title = 'Anúncio patrocinado – Kit 7 Camisetas Masculina Manga Curta Lisa Algodão Premium'
        self.offer.current_price = Decimal('125.30')
        self.offer.original_price = Decimal('155.44')
        self.offer.discount_pct = Decimal('19.00')
        self.offer.save(update_fields=['title', 'current_price', 'original_price', 'discount_pct'])
        _batch, item = self._create_ready_batch(
            caption=(
                '🤖 Trecho do agente descontos-bot: Anúncio patrocinado – Kit 7 Camisetas '
                'Masculina Manga Curta Lisa Algodão Premium por R$ 125,30, com 19% OFF. '
                'Curadoria destacou a oportunidade pelo preço e desconto do marketplace Amazon.'
            )
        )
        item.final_title = 'Kit 7 Camisetas Masculina Manga Curta Lisa Algodão Premium com 19% OFF'

        payload = build_curated_telegram_payload(item, self.channel)

        self.assertIn('<b>📦 Kit 7 Camisetas Masculina Manga Curta Lisa Algodão Premium com 19% OFF</b>', payload.caption)
        self.assertIn('🤖 Trecho do agente descontos-bot:', payload.caption)
        highlight = payload.caption.split('🤖 Trecho do agente descontos-bot:', 1)[1].split('\n\n💰', 1)[0]
        self.assertNotIn('Kit 7 Camisetas', highlight)
        self.assertNotIn('R$ 125,30', highlight)
        self.assertNotIn('19% OFF', highlight)
        self.assertIn('💰 <s>De R$ 155,44</s>', payload.caption)
        self.assertIn('✅ <b>Por apenas R$ 125,30</b>', payload.caption)

    def test_without_ai_curation_keeps_legacy_selector_flow(self):
        out = StringIO()

        call_command(
            'publish_telegram',
            '--once',
            '--channel',
            'telegram_homolog',
            '--dry-run',
            stdout=out,
        )

        text = out.getvalue()
        self.assertIn('Selecionadas', text)
        self.assertIn('Título selector antigo Telegram', text)
        self.assertNotIn('Lote curado #', text)
        self.assertEqual(Delivery.objects.count(), 0)
