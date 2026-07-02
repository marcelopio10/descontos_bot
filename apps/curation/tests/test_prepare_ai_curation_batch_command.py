import json
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class PrepareAICurationBatchCommandTests(TestCase):
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
        now = timezone.now()
        offer_id = 1
        for marketplace_code in ('mercadolivre', 'amazon', 'shopee'):
            for index in range(3):
                Offer.objects.create(
                    marketplace=self.marketplaces[marketplace_code],
                    external_id=f'{marketplace_code}-{index}',
                    title=f'Oferta {marketplace_code} {index}',
                    normalized_title=f'oferta {marketplace_code} {index}',
                    offer_hash=f'hash-s5-{offer_id}',
                    slug=f'oferta-{marketplace_code}-{index}',
                    current_price=Decimal('99.90'),
                    original_price=Decimal('199.80'),
                    discount_pct=Decimal('50.00'),
                    product_url='https://example.com/produto-sensivel',
                    affiliate_url='https://example.com/afiliado-sensivel',
                    image_url='https://example.com/img.jpg',
                    is_active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    price_collected_at=now,
                )
                offer_id += 1

    def test_prepare_command_creates_controlled_batch_and_public_sanitized_json(self):
        with TemporaryDirectory() as tmpdir:
            audit_dir = Path(tmpdir) / 'audit'
            public_dir = Path(tmpdir) / 'public'
            out = StringIO()

            call_command(
                'prepare_ai_curation_batch',
                '--channel',
                'whatsapp_main',
                '--mode',
                'dry_run',
                '--candidate-limit',
                '6',
                '--dry-run',
                '--skip-images',
                '--audit-dir',
                str(audit_dir),
                '--public-dir',
                str(public_dir),
                stdout=out,
            )

            run = CurationRun.objects.latest('id')
            batch = run.batch
            self.assertEqual(run.status, CurationRun.Status.COMPLETED)
            self.assertEqual(run.mode, CurationRun.Mode.DRY_RUN)
            self.assertEqual(run.candidate_count, 6)
            self.assertEqual(batch.status, CuratedBatch.Status.READY)
            self.assertEqual(batch.items.count(), 6)
            self.assertEqual(Delivery.objects.count(), 0)
            self.assertIn('nenhum envio real foi chamado', out.getvalue())
            self.assertTrue(run.public_json_path)

            public_payload = json.loads(Path(run.public_json_path).read_text(encoding='utf-8'))
            serialized = json.dumps(public_payload, ensure_ascii=False)
            self.assertEqual(public_payload['run']['id'], run.id)
            self.assertEqual(public_payload['batch']['status'], CuratedBatch.Status.READY)
            self.assertIn('decisions', public_payload)
            self.assertNotIn('affiliate_url', serialized)
            self.assertNotIn('product_url', serialized)
            self.assertNotIn('raw_ai_json', serialized)
            self.assertNotIn('afiliado-sensivel', serialized)

            inspect_out = StringIO()
            call_command('inspect_ai_curation_batch', '--channel', 'whatsapp_main', stdout=inspect_out)
            inspect_text = inspect_out.getvalue()
            self.assertIn(f'Run #{run.id}', inspect_text)
            self.assertIn('Distribuição', inspect_text)
            self.assertIn('Decisões', inspect_text)
            self.assertIn('Rejeições', inspect_text)

    def test_shadow_flag_forces_shadow_mode(self):
        with TemporaryDirectory() as tmpdir:
            call_command(
                'prepare_ai_curation_batch',
                '--channel',
                'whatsapp_main',
                '--mode',
                'dry_run',
                '--candidate-limit',
                '3',
                '--shadow',
                '--audit-dir',
                str(Path(tmpdir) / 'audit'),
                '--public-dir',
                str(Path(tmpdir) / 'public'),
                stdout=StringIO(),
            )

        run = CurationRun.objects.latest('id')
        self.assertEqual(run.mode, CurationRun.Mode.SHADOW)
        self.assertEqual(Delivery.objects.count(), 0)
