from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.curated_batch_reader import get_ready_curated_batch
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class CuratedBatchReaderTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Main',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='ml-reader-1',
            title='Oferta reader test',
            normalized_title='oferta reader test',
            offer_hash='hash-reader-1',
            slug='oferta-reader-test',
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

    def _create_batch(self, mode: str) -> CuratedBatch:
        run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=mode,
            profile_name='descontos-bot',
            model_provider='openai-codex',
            model_name='gpt-5.5',
            candidate_count=1,
            selected_count=1,
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=self.offer,
            marketplace_code='mercadolivre',
            ai_score=Decimal('80'),
            ai_classification=CurationDecision.Classification.APPROVED,
            decision_reason='ok',
            title_original=self.offer.title,
            title_rewritten='Título curado',
            caption_rewritten='Caption',
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
        CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=self.offer,
            position=1,
            final_title='Título curado',
            final_caption_whatsapp='Caption WhatsApp',
            final_caption_telegram='Caption Telegram',
            final_image_url='https://example.com/img.jpg',
        )
        return batch

    def test_returns_batch_without_mode_filter(self):
        batch = self._create_batch(CurationRun.Mode.DRY_RUN)
        result = get_ready_curated_batch(self.channel)
        self.assertTrue(result.has_batch)
        self.assertEqual(result.batch.id, batch.id)

    def test_allowed_modes_filters_out_dry_run_batch_when_real_modes_required(self):
        self._create_batch(CurationRun.Mode.DRY_RUN)
        result = get_ready_curated_batch(
            self.channel,
            allowed_modes=[CurationRun.Mode.HOMOLOG, CurationRun.Mode.PRODUCTION],
        )
        self.assertFalse(result.has_batch)
        self.assertIn('Nenhum lote curado pronto', result.reason)

    def test_allowed_modes_returns_homolog_batch_when_real_modes_required(self):
        batch = self._create_batch(CurationRun.Mode.HOMOLOG)
        result = get_ready_curated_batch(
            self.channel,
            allowed_modes=[CurationRun.Mode.HOMOLOG, CurationRun.Mode.PRODUCTION],
        )
        self.assertTrue(result.has_batch)
        self.assertEqual(result.batch.id, batch.id)

    def test_allowed_modes_filters_out_homolog_batch_when_dry_run_mode_required(self):
        self._create_batch(CurationRun.Mode.HOMOLOG)
        result = get_ready_curated_batch(
            self.channel,
            allowed_modes=[CurationRun.Mode.DRY_RUN],
        )
        self.assertFalse(result.has_batch)

    def test_allowed_modes_returns_dry_run_batch_when_dry_run_mode_required(self):
        batch = self._create_batch(CurationRun.Mode.DRY_RUN)
        result = get_ready_curated_batch(
            self.channel,
            allowed_modes=[CurationRun.Mode.DRY_RUN],
        )
        self.assertTrue(result.has_batch)
        self.assertEqual(result.batch.id, batch.id)

    def test_expired_batch_is_not_returned(self):
        run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.DRY_RUN,
            profile_name='descontos-bot',
            model_provider='mock',
            model_name='fake',
            candidate_count=1,
            selected_count=1,
        )
        CuratedBatch.objects.create(
            run=run,
            channel=self.channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=timezone.now() - timezone.timedelta(hours=1),
        )
        result = get_ready_curated_batch(self.channel)
        self.assertFalse(result.has_batch)
