from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.message_builder import build_curated_offer_message
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class AICuratedWhatsAppTemplateTests(TestCase):
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
            external_id='template-regression-1',
            title='Sabão Líquido Omo Lavagem Perfeita 5l',
            normalized_title='sabao liquido omo lavagem perfeita 5l',
            offer_hash='template-regression-1',
            slug='sabao-liquido-omo-lavagem-perfeita-5l',
            current_price=Decimal('48.00'),
            original_price=Decimal('63.00'),
            discount_pct=Decimal('22.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://meli.la/22FoCsY',
            image_url='https://example.com/image.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Homologação',
            code='whatsapp_main',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='descontos.bot - Homologação',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )
        run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.HOMOLOG,
            candidate_count=1,
            selected_count=1,
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=self.channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=now + timezone.timedelta(hours=1),
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=self.offer,
            marketplace_code='mercadolivre',
            ai_score=Decimal('95'),
            ai_classification=CurationDecision.Classification.APPROVED,
            decision_reason='Boa oferta.',
            title_original=self.offer.title,
            title_rewritten='Sabão Líquido Omo 5L com 22% OFF',
            caption_rewritten=(
                'Sabão Omo 5 litros por R$ 48,00. Boa compra para abastecer a lavanderia.'
            ),
            raw_ai_json={},
            is_selected_for_batch=True,
        )
        self.item = CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=self.offer,
            position=1,
            final_title='Sabão Líquido Omo 5L com 22% OFF',
            final_caption_whatsapp=(
                'Sabão Omo 5 litros por R$ 48,00. Boa compra para abastecer a lavanderia.'
            ),
        )

    def test_curated_whatsapp_caption_preserves_original_sales_template_with_link(self):
        message = build_curated_offer_message(self.item, self.channel)

        self.assertIn('📦 *Sabão Líquido Omo 5L com 22% OFF*', message)
        self.assertIn('⚡ *BOT ACHOU DESCONTO* ⚡', message)
        self.assertIn('💰 ~De R$ 63,00~', message)
        self.assertIn('✅ *Por apenas R$ 48,00*', message)
        self.assertIn('🏷️ *22% OFF*', message)
        self.assertIn('🛒 Compre aqui 👇', message)
        self.assertIn('https://meli.la/22FoCsY', message)
        self.assertIn('utm_source=whatsapp', message)
        self.assertIn('⏰ Oferta por tempo limitado!', message)
        self.assertIn('🤖 @descontos.bot', message)

    def test_curated_whatsapp_caption_does_not_send_plain_ai_paragraph_as_entire_message(self):
        message = build_curated_offer_message(self.item, self.channel)

        self.assertNotEqual(message, self.item.final_caption_whatsapp)
        self.assertLess(message.index('🛒 Compre aqui 👇'), message.index('⏰ Oferta por tempo limitado!'))

    def test_agent_highlight_removes_repetitive_title_price_and_discount(self):
        self.item.final_title = 'Kit 7 Camisetas Masculina Manga Curta Lisa Algodão Premium com 19% OFF'
        self.item.final_caption_whatsapp = (
            '🤖 Trecho do agente descontos-bot: Anúncio patrocinado – Kit 7 Camisetas '
            'Masculina Manga Curta Lisa Algodão Premium por R$ 125,30, com 19% OFF. '
            'Curadoria destacou a oportunidade pelo preço e desconto do marketplace Amazon.'
        )
        self.offer.title = 'Anúncio patrocinado – Kit 7 Camisetas Masculina Manga Curta Lisa Algodão Premium'
        self.offer.current_price = Decimal('125.30')
        self.offer.original_price = Decimal('155.44')
        self.offer.discount_pct = Decimal('19.00')
        self.offer.save(update_fields=['title', 'current_price', 'original_price', 'discount_pct'])

        message = build_curated_offer_message(self.item, self.channel)
        highlight = message.split('✨ ', 1)[1].split('\n\n💰', 1)[0]

        self.assertIn('🤖 Trecho do agente descontos-bot:', highlight)
        self.assertNotIn('Kit 7 Camisetas', highlight)
        self.assertNotIn('R$ 125,30', highlight)
        self.assertNotIn('19% OFF', highlight)
        self.assertIn('boa opção', highlight.lower())

    def test_agent_highlight_avoids_formal_marketing_language(self):
        self.offer.title = 'Kit 8 peças Mordedor para Bebe Sensorial Macio com Chocalho'
        self.offer.save(update_fields=['title'])
        self.item.final_caption_whatsapp = (
            '🤖 Trecho do agente descontos-bot: Kit 8 peças Mordedor para Bebe Sensorial '
            'Macio com Chocalho por R$ 22,80, com 43% OFF. Curadoria destacou a oportunidade '
            'pelo preço e desconto do marketplace Shopee.'
        )

        message = build_curated_offer_message(self.item, self.channel)
        highlight = message.split('✨ ', 1)[1].split('\n\n💰', 1)[0]

        self.assertNotIn('apelo', highlight.lower())
        self.assertNotIn('uso diário', highlight.lower())
        self.assertIn('dentinhos', highlight.lower())
