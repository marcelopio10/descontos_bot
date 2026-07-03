from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.ai_schema import validate_agent_output
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class ImageProcessingTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Main',
            code='whatsapp_main',
            target='descontos.bot',
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
            external_id='offer-1',
            title='Oferta Boa',
            normalized_title='oferta boa',
            offer_hash='s6-offer-1',
            slug='s6-offer-1',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/image.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )
        self.run = CurationRun.objects.create(
            channel=self.channel,
            status=CurationRun.Status.COMPLETED,
            mode=CurationRun.Mode.DRY_RUN,
            candidate_count=1,
            selected_count=1,
        )
        self.decision = CurationDecision.objects.create(
            run=self.run,
            offer=self.offer,
            marketplace_code='mercadolivre',
            ai_classification=CurationDecision.Classification.APPROVED,
            title_original=self.offer.title,
            title_rewritten='Oferta Boa',
            caption_rewritten='Oferta boa validada',
            image_analysis_json={'decision': 'approved'},
            is_selected_for_batch=True,
        )
        self.batch = CuratedBatch.objects.create(
            run=self.run,
            channel=self.channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=timezone.now() + timedelta(hours=36),
        )
        self.item = CuratedBatchItem.objects.create(
            batch=self.batch,
            decision=self.decision,
            offer=self.offer,
            position=1,
            final_title='Oferta Boa',
            final_caption_whatsapp='Oferta boa validada',
            final_caption_telegram='Oferta boa validada',
            final_image_url=self.offer.image_url,
        )

    def test_selected_image_is_downloaded_resized_and_saved_locally(self):
        from apps.curation.services.image_processing import process_selected_batch_images

        with TemporaryDirectory() as tmpdir:
            result = process_selected_batch_images(
                self.batch,
                media_root=Path(tmpdir),
                fetcher=lambda url: _image_bytes(size=(1800, 1200)),
            )

            self.item.refresh_from_db()
            self.decision.refresh_from_db()
            self.assertEqual(result.processed, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue(self.item.local_image_path)
            saved_path = Path(self.item.local_image_path)
            self.assertTrue(saved_path.exists())
            with Image.open(saved_path) as image:
                self.assertLessEqual(max(image.size), 1280)
                self.assertEqual(image.format, 'JPEG')
            self.assertEqual(self.item.image_mime_type, 'image/jpeg')
            self.assertGreater(self.item.image_width or 0, 0)
            self.assertEqual(self.decision.image_analysis_json['status'], 'processed')
            self.assertTrue(self.decision.image_analysis_json['multimodal_ready'])

    def test_broken_image_url_marks_replacement_without_crashing(self):
        from apps.curation.services.image_processing import ImageProcessingError, process_selected_batch_images

        with TemporaryDirectory() as tmpdir:
            result = process_selected_batch_images(
                self.batch,
                media_root=Path(tmpdir),
                fetcher=lambda url: (_ for _ in ()).throw(ImageProcessingError('HTTP 404')),
            )

            self.item.refresh_from_db()
            self.decision.refresh_from_db()
            self.assertEqual(result.processed, 0)
            self.assertEqual(result.failed, 1)
            self.assertEqual(self.item.local_image_path, '')
            self.assertEqual(self.decision.image_analysis_json['status'], 'needs_replacement')
            self.assertIn('HTTP 404', self.decision.image_analysis_json['error'])

    def test_low_quality_image_marks_replacement(self):
        from apps.curation.services.image_processing import process_selected_batch_images

        with TemporaryDirectory() as tmpdir:
            result = process_selected_batch_images(
                self.batch,
                media_root=Path(tmpdir),
                fetcher=lambda url: _image_bytes(size=(120, 120)),
            )

            self.decision.refresh_from_db()
            self.assertEqual(result.processed, 0)
            self.assertEqual(result.failed, 1)
            self.assertEqual(self.decision.image_analysis_json['status'], 'needs_replacement')
            self.assertEqual(self.decision.image_analysis_json['reason'], 'image_too_small')

    def test_cleanup_curation_media_dry_run_and_delete_old_files(self):
        with TemporaryDirectory() as tmpdir:
            media_root = Path(tmpdir)
            old_file = media_root / 'curation' / 'old.jpg'
            new_file = media_root / 'curation' / 'new.jpg'
            old_file.parent.mkdir(parents=True)
            old_file.write_bytes(b'old')
            new_file.write_bytes(b'new')
            old_timestamp = (timezone.now() - timedelta(hours=40)).timestamp()
            old_file.touch()
            new_file.touch()
            import os
            os.utime(old_file, (old_timestamp, old_timestamp))

            out = StringIO()
            call_command('cleanup_curation_media', '--media-root', str(media_root), '--dry-run', stdout=out)
            self.assertTrue(old_file.exists())
            self.assertIn('would_delete=1', out.getvalue())

            out = StringIO()
            call_command('cleanup_curation_media', '--media-root', str(media_root), stdout=out)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
            self.assertIn('deleted=1', out.getvalue())

    def test_agent_output_rejects_improper_selected_image_decision(self):
        payload = {
            'schema_version': '1.0',
            'actual_distribution': {'mercadolivre': 1},
            'decisions': [
                {
                    'offer_id': self.offer.id,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 90,
                    'relevance_score': 90,
                    'discount_quality_score': 90,
                    'audience_fit_score': 90,
                    'reason': 'ok',
                    'rewritten_title': 'Oferta Boa',
                    'rewritten_caption_whatsapp': 'Oferta boa',
                    'rewritten_caption_telegram': 'Oferta boa',
                    'image_required': True,
                    'image_decision': 'improper',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            ],
        }

        result = validate_agent_output(payload, expected_offer_ids={self.offer.id})
        self.assertFalse(result.is_valid)
        self.assertTrue(any('imagem imprópria' in error for error in result.errors))


def _image_bytes(*, size: tuple[int, int], color: tuple[int, int, int] = (230, 80, 40)) -> bytes:
    image = Image.new('RGB', size, color)
    output = BytesIO()
    image.save(output, format='JPEG', quality=92)
    return output.getvalue()
