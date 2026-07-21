from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CurationBlacklistTerm, CurationDecision, CurationRun
from apps.curation.services.ai_curator import prepare_ai_curation_batch
from apps.curation.services.hermes_runner import FakeHermesRunner
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class AICuratorTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Main',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.marketplaces = {
            code: Marketplace.objects.create(
                name=name,
                code=code,
                base_url=f'https://{code}.example.com',
                is_active=True,
            )
            for code, name in (
                ('mercadolivre', 'Mercado Livre'),
                ('amazon', 'Amazon'),
                ('shopee', 'Shopee'),
            )
        }
        self.offers = []
        now = timezone.now()
        offer_id = 1
        for marketplace_code in ('mercadolivre', 'amazon', 'shopee'):
            for index in range(3):
                self.offers.append(
                    Offer.objects.create(
                        marketplace=self.marketplaces[marketplace_code],
                        external_id=f'{marketplace_code}-{index}',
                        title=f'Oferta {marketplace_code} {index}',
                        normalized_title=f'oferta {marketplace_code} {index}',
                        offer_hash=f'hash-s4-{offer_id}',
                        slug=f'oferta-{marketplace_code}-{index}',
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
                )
                offer_id += 1

    def test_mock_hermes_creates_ready_batch_with_audit_json(self):
        with TemporaryDirectory() as tmpdir:
            result = prepare_ai_curation_batch(
                channel=self.channel,
                offers=self.offers,
                runner=FakeHermesRunner(),
                mode=CurationRun.Mode.DRY_RUN,
                batch_size=6,
                audit_dir=Path(tmpdir),
            )
            run = result.run
            batch = result.batch
            self.assertTrue(run.input_json_path)
            self.assertTrue(run.output_json_path)
            self.assertTrue(Path(run.input_json_path).exists())
            self.assertTrue(Path(run.output_json_path).exists())

        self.assertEqual(run.status, CurationRun.Status.COMPLETED)
        self.assertEqual(run.candidate_count, 9)
        self.assertEqual(run.selected_count, 6)
        self.assertEqual(CurationDecision.objects.filter(run=run).count(), 9)
        self.assertIsNotNone(batch)
        self.assertEqual(batch.status, CuratedBatch.Status.READY)
        self.assertEqual(batch.items.count(), 6)
        self.assertEqual(list(batch.items.values_list('position', flat=True)), [1, 2, 3, 4, 5, 6])

    @patch('apps.curation.services.ai_curator.alertar_curadoria_falhas_consecutivas')
    def test_runner_failure_marks_run_failed_and_does_not_create_ready_batch(self, mock_alert):
        result = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:2],
            runner=FakeHermesRunner(should_fail=True),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )

        self.assertEqual(result.run.status, CurationRun.Status.FAILED)
        self.assertIn('falha simulada', result.run.error_message)
        self.assertIsNone(result.batch)
        self.assertFalse(CuratedBatch.objects.filter(run=result.run, status=CuratedBatch.Status.READY).exists())
        # Uma única falha ainda não atinge o limiar de alerta (2 seguidas).
        mock_alert.assert_not_called()

    @patch('apps.curation.services.ai_curator.alertar_curadoria_falhas_consecutivas')
    def test_invalid_runner_output_marks_run_failed_and_does_not_create_ready_batch(self, mock_alert):
        result = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:2],
            runner=FakeHermesRunner(forced_payload={'schema_version': '1.0', 'decisions': 'invalid'}),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )

        self.assertEqual(result.run.status, CurationRun.Status.FAILED)
        self.assertIn('decisions deve ser lista', result.run.error_message)
        self.assertIsNone(result.batch)
        self.assertFalse(CurationDecision.objects.filter(run=result.run).exists())
        self.assertFalse(CuratedBatch.objects.filter(run=result.run, status=CuratedBatch.Status.READY).exists())
        mock_alert.assert_not_called()

    @patch('apps.curation.services.ai_curator.alertar_curadoria_falhas_consecutivas')
    def test_second_consecutive_failure_for_same_channel_triggers_operator_alert(self, mock_alert):
        first = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:2],
            runner=FakeHermesRunner(should_fail=True),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )
        self.assertEqual(first.run.status, CurationRun.Status.FAILED)
        mock_alert.assert_not_called()

        second = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:2],
            runner=FakeHermesRunner(should_fail=True),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )
        self.assertEqual(second.run.status, CurationRun.Status.FAILED)
        mock_alert.assert_called_once_with(
            channel_code=self.channel.code,
            run_id=second.run.id,
            total_falhas=2,
        )

    def test_improper_output_is_persisted_but_not_selected(self):
        # AI rejects improper offer and selects the approved one
        forced_payload = {
            'schema_version': '1.0',
            'actual_distribution': {},
            'decisions': [
                {
                    'offer_id': self.offers[0].id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'improper',
                    'selected_for_batch': False,
                    'batch_position': None,
                    'conversion_score': 0,
                    'relevance_score': 0,
                    'discount_quality_score': 0,
                    'audience_fit_score': 0,
                    'reason': 'Tema proibido.',
                    'rewritten_title': self.offers[0].title,
                    'rewritten_caption_whatsapp': '',
                    'rewritten_caption_telegram': '',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [{'term': 'arma de brinquedo'}],
                    'risk_flags': [],
                },
                {
                    'offer_id': self.offers[1].id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 90,
                    'relevance_score': 90,
                    'discount_quality_score': 90,
                    'audience_fit_score': 90,
                    'reason': 'Boa oferta.',
                    'rewritten_title': 'Oferta boa',
                    'rewritten_caption_whatsapp': 'Caption W',
                    'rewritten_caption_telegram': 'Caption T',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                },
            ],
        }

        result = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:2],
            runner=FakeHermesRunner(forced_payload=forced_payload),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )

        self.assertEqual(result.run.status, CurationRun.Status.COMPLETED)
        self.assertEqual(result.batch.items.count(), 1)
        self.assertEqual(result.batch.items.get().offer_id, self.offers[1].id)
        improper = CurationDecision.objects.get(run=result.run, offer=self.offers[0])
        self.assertEqual(improper.ai_classification, CurationDecision.Classification.IMPROPER)
        self.assertFalse(improper.is_selected_for_batch)
        audit = CurationBlacklistTerm.objects.get(decision=improper)
        self.assertEqual(audit.normalized_term, 'arma de brinquedo')
        self.assertEqual(audit.run, result.run)

    def test_two_offers_same_produto_canonico_id_only_one_enters_batch(self):
        # Sprint 5 / achado P8: mesmo produto (ex. mesmo ASIN), dois "vendedores"/
        # capturas diferentes — a IA aprova e seleciona as duas, mas o batch
        # optimizer deve manter só uma (maior ai_score) no lote final.
        offer_a, offer_b = self.offers[0], self.offers[1]
        offer_a.produto_canonico_id = 'amazon:B0SAMEPROD'
        offer_a.save(update_fields=['produto_canonico_id'])
        offer_b.produto_canonico_id = 'amazon:B0SAMEPROD'
        offer_b.save(update_fields=['produto_canonico_id'])

        forced_payload = {
            'schema_version': '1.0',
            'actual_distribution': {},
            'decisions': [
                {
                    'offer_id': offer_a.id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 95,
                    'relevance_score': 95,
                    'discount_quality_score': 95,
                    'audience_fit_score': 95,
                    'reason': 'Melhor preço entre os vendedores.',
                    'rewritten_title': 'Oferta vendedor A',
                    'rewritten_caption_whatsapp': 'Caption W A',
                    'rewritten_caption_telegram': 'Caption T A',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                },
                {
                    'offer_id': offer_b.id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 2,
                    'conversion_score': 60,
                    'relevance_score': 60,
                    'discount_quality_score': 60,
                    'audience_fit_score': 60,
                    'reason': 'Mesmo produto, vendedor B.',
                    'rewritten_title': 'Oferta vendedor B',
                    'rewritten_caption_whatsapp': 'Caption W B',
                    'rewritten_caption_telegram': 'Caption T B',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                },
            ],
        }

        result = prepare_ai_curation_batch(
            channel=self.channel,
            offers=[offer_a, offer_b],
            runner=FakeHermesRunner(forced_payload=forced_payload),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=2,
        )

        self.assertEqual(result.run.status, CurationRun.Status.COMPLETED)
        self.assertEqual(result.batch.items.count(), 1)
        self.assertEqual(result.batch.items.get().offer_id, offer_a.id)

    def test_zero_selected_does_not_create_ready_batch_and_marks_run_failed(self):
        # AI returns all offers with selected_for_batch=False → safety gate produces empty batch
        forced_payload = {
            'schema_version': '1.0',
            'actual_distribution': {},
            'decisions': [
                {
                    'offer_id': self.offers[0].id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': False,
                    'batch_position': None,
                    'conversion_score': 70,
                    'relevance_score': 70,
                    'discount_quality_score': 70,
                    'audience_fit_score': 70,
                    'reason': 'Não selecionada pela IA.',
                    'rewritten_title': 'Oferta não selecionada',
                    'rewritten_caption_whatsapp': 'Caption W',
                    'rewritten_caption_telegram': 'Caption T',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                },
            ],
        }

        result = prepare_ai_curation_batch(
            channel=self.channel,
            offers=self.offers[:1],
            runner=FakeHermesRunner(forced_payload=forced_payload),
            mode=CurationRun.Mode.DRY_RUN,
            batch_size=1,
        )

        self.assertEqual(result.run.status, CurationRun.Status.FAILED)
        self.assertIn('Nenhum item aprovado e selecionado', result.run.error_message)
        self.assertIsNone(result.batch)
        self.assertFalse(CuratedBatch.objects.filter(run=result.run, status=CuratedBatch.Status.READY).exists())
