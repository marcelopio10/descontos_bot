from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.models import (
    CuratedBatch,
    CuratedBatchItem,
    CurationBlacklistTerm,
    CurationDecision,
    CurationRun,
)
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class AICurationModelTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Main',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='abc',
            title='Tênis Adidas Runfalcon Masculino Oferta Especial',
            normalized_title='tenis adidas runfalcon masculino oferta especial',
            offer_hash='hash-ai-curation-model',
            slug='tenis-adidas-runfalcon',
            current_price=Decimal('199.90'),
            original_price=Decimal('399.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_create_run_decision_batch_and_item(self):
        run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.DRY_RUN,
            profile_name='descontos.bot',
            candidate_count=1,
            selected_count=1,
            target_distribution_json={'mercadolivre': 1},
            actual_distribution_json={'mercadolivre': 1},
            observer_context_json={'messages_analyzed': 0},
            baseline_summary_json={'candidate_count': 1},
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=self.offer,
            marketplace_code='mercadolivre',
            baseline_score=Decimal('80.00'),
            baseline_classification='boa',
            baseline_decision='publicar',
            ai_score=Decimal('91.00'),
            ai_classification=CurationDecision.Classification.APPROVED,
            conversion_score=Decimal('90.00'),
            relevance_score=Decimal('88.00'),
            discount_quality_score=Decimal('92.00'),
            audience_fit_score=Decimal('89.00'),
            decision_reason='Marca conhecida e desconto forte.',
            title_original=self.offer.title,
            title_rewritten='Tênis Adidas Runfalcon com 50% off',
            caption_rewritten='Oferta honesta com desconto real.',
            raw_ai_json={'offer_id': self.offer.id},
            is_selected_for_batch=True,
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=self.channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            target_distribution_json={'mercadolivre': 1},
            actual_distribution_json={'mercadolivre': 1},
        )
        item = CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=self.offer,
            position=1,
            final_title='Tênis Adidas Runfalcon com 50% off',
            final_caption_whatsapp='WhatsApp caption',
            final_caption_telegram='Telegram caption',
            final_image_url=self.offer.image_url,
        )

        self.assertEqual(run.decisions.count(), 1)
        self.assertEqual(batch.items.count(), 1)
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.PENDING)
        self.assertEqual(decision.batch_item, item)

    def test_create_automatic_blacklist_audit_term(self):
        run = CurationRun.objects.create(channel=self.channel, mode=CurationRun.Mode.DRY_RUN)
        decision = CurationDecision.objects.create(
            run=run,
            offer=self.offer,
            marketplace_code='mercadolivre',
            ai_classification=CurationDecision.Classification.IMPROPER,
            decision_reason='Termo impróprio detectado.',
        )

        term = CurationBlacklistTerm.objects.create(
            term='arma de brinquedo',
            normalized_term='arma de brinquedo',
            source=CurationBlacklistTerm.Source.AI_TEXT_MODERATION,
            offer=self.offer,
            decision=decision,
            run=run,
        )

        self.assertEqual(term.status, CurationBlacklistTerm.Status.ACTIVE)
        self.assertEqual(run.blacklist_terms.get(), term)
