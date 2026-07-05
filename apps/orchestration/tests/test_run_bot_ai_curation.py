from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class RunBotAICurationTests(TestCase):
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
            external_id='ml-s10-1',
            title='Título selector antigo',
            normalized_title='titulo selector antigo',
            offer_hash='hash-s10-1',
            slug='titulo-selector-antigo',
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

    def _create_ready_batch(self):
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
            marketplace_code='mercadolivre',
            ai_score=Decimal('90'),
            ai_classification=CurationDecision.Classification.APPROVED,
            conversion_score=Decimal('90'),
            relevance_score=Decimal('90'),
            discount_quality_score=Decimal('90'),
            audience_fit_score=Decimal('90'),
            decision_reason='Boa oferta curada.',
            title_original=self.offer.title,
            title_rewritten='Título curado pela IA',
            caption_rewritten='Caption WhatsApp curada pela IA',
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
            final_title='Título curado pela IA',
            final_caption_whatsapp='Caption WhatsApp curada pela IA',
            final_caption_telegram='Caption Telegram curada pela IA',
            final_image_url='https://example.com/img-final.jpg',
        )
        return batch

    def test_dry_run_ai_curation_prints_ready_batch_without_delivery(self):
        batch = self._create_ready_batch()
        out = StringIO()

        with patch('apps.orchestration.management.commands.run_bot.call_command'):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                '--ai-curation',
                stdout=out,
            )

        text = out.getvalue()
        self.assertIn(f'Lote curado #{batch.id}', text)
        self.assertIn('Título curado pela IA', text)
        self.assertIn('Caption WhatsApp curada pela IA', text)
        self.assertIn('dry_run ativo', text)
        self.assertEqual(Delivery.objects.count(), 0)
        batch.refresh_from_db()
        self.assertIsNone(batch.consumed_at)
        self.assertEqual(batch.status, CuratedBatch.Status.READY)

    def test_ai_curation_without_ready_batch_pauses_without_selector_fallback(self):
        out = StringIO()

        with patch('apps.orchestration.management.commands.run_bot.call_command'):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                '--ai-curation',
                stdout=out,
            )

        text = out.getvalue()
        self.assertIn('Nenhum lote curado pronto', text)
        self.assertNotIn('Título selector antigo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_default_flow_prepares_ai_curation_and_blocks_legacy_selector_fallback(self):
        out = StringIO()

        with patch('apps.orchestration.management.commands.run_bot.call_command') as prepare:
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                stdout=out,
            )

        text = out.getvalue()
        prepare.assert_called_once()
        args = prepare.call_args.args
        self.assertEqual(args[:3], ('prepare_ai_curation_batch', '--channel', 'whatsapp_main'))
        self.assertIn('--runner', args)
        self.assertIn('real', args)
        self.assertIn('--profile', args)
        self.assertIn('descontos-bot', args)
        self.assertIn('--dry-run', args)
        self.assertIn('Nenhum lote curado pronto', text)
        self.assertNotIn('Título selector antigo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_legacy_selector_flag_keeps_old_selector_flow(self):
        out = StringIO()

        call_command(
            'run_bot',
            '--dry-run',
            '--once',
            '--skip-scraping',
            '--channel',
            'whatsapp_main',
            '--legacy-selector',
            stdout=out,
        )

        text = out.getvalue()
        self.assertIn('Ofertas selecionadas:', text)
        self.assertIn('Título selector antigo', text)
        self.assertNotIn('Lote curado #', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_ai_curation_required_pauses_without_selector_fallback(self):
        out = StringIO()

        with patch('apps.orchestration.management.commands.run_bot.call_command'):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                '--ai-curation-required',
                stdout=out,
            )

        text = out.getvalue()
        self.assertIn('Nenhum lote curado pronto', text)
        self.assertNotIn('Título selector antigo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_prepare_command_error_when_ai_required_aborts_without_legacy_fallback(self):
        out = StringIO()

        with patch(
            'apps.orchestration.management.commands.run_bot.call_command',
            side_effect=CommandError('runner falhou: sessão expirada'),
        ):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                stdout=out,
            )

        text = out.getvalue()
        self.assertIn('Preparação IA falhou', text)
        self.assertIn('Nenhum lote curado pronto', text)
        self.assertIn('ai-curation-required: abortando ciclo', text)
        self.assertNotIn('Ofertas selecionadas:', text)
        self.assertNotIn('Título selector antigo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_prepare_command_error_with_ready_batch_still_consumes_batch(self):
        batch = self._create_ready_batch()
        out = StringIO()

        with patch(
            'apps.orchestration.management.commands.run_bot.call_command',
            side_effect=CommandError('runner falhou: sessão expirada'),
        ):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                stdout=out,
            )

        text = out.getvalue()
        self.assertIn('Preparação IA falhou', text)
        self.assertIn(f'Lote curado #{batch.id}', text)
        self.assertIn('Título curado pela IA', text)
        self.assertNotIn('ai-curation-required: abortando ciclo', text)
        self.assertEqual(Delivery.objects.count(), 0)

    def test_prepare_ai_curation_invokes_prepare_command_before_reading_batch(self):
        out = StringIO()

        with patch('apps.orchestration.management.commands.run_bot.call_command') as prepare:
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                'whatsapp_main',
                '--ai-curation',
                '--prepare-ai-curation',
                stdout=out,
            )

        prepare.assert_called_once()
        args = prepare.call_args.args
        self.assertEqual(args[:3], ('prepare_ai_curation_batch', '--channel', 'whatsapp_main'))
        self.assertIn('--dry-run', args)
        self.assertIn('--skip-images', args)
        self.assertIn('Preparando lote de curadoria IA', out.getvalue())
        self.assertEqual(Delivery.objects.count(), 0)
