import json
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.curation.management.commands.prepare_ai_curation_batch import _balanced_marketplace_candidates
from apps.curation.models import CuratedBatch, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
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
            call_command('inspect_ai_curation_batch', '--channel', 'whatsapp_main', '--compare-selector', stdout=inspect_out)
            inspect_text = inspect_out.getvalue()
            self.assertIn(f'Run #{run.id}', inspect_text)
            self.assertIn('Distribuição', inspect_text)
            self.assertIn('Comparação selector atual vs agente', inspect_text)
            self.assertIn('Decisões', inspect_text)
            self.assertIn('Rejeições', inspect_text)

    def test_observer_context_is_real_sanitized_signal_not_the_old_static_dict(self):
        """Sprint 6 / Tarefa 6.2 (achado P3): antes, observer_context_json era
        sempre {'source': ..., 'skip_images': ..., 'real_send_enabled': False}
        — nunca refletia nada do que o observer via de fato. Agora precisa
        conter o resultado real (e sanitizado) de build_observer_context(),
        mesclado com esses 3 campos de metadado do comando, e nunca dado
        bruto/sensível (jid, texto, sender_hash, URL).
        """
        group = ObservedWhatsAppGroup.objects.create(name='Grupo Ofertas', jid='999@g.us')
        now = timezone.now()
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='msg-radar-1',
            sender_hash='hash-sender-secreto',
            sent_at=now,
            collected_at=now,
            text='Texto bruto com https://example.com/oferta-secreta',
            urls=['https://example.com/oferta-secreta'],
            has_image=True,
            parsed_marketplace='mercadolivre',
            editorial_labels=['cupom', 'desconto_50'],
        )

        with TemporaryDirectory() as tmpdir:
            call_command(
                'prepare_ai_curation_batch',
                '--channel',
                'whatsapp_main',
                '--mode',
                'dry_run',
                '--candidate-limit',
                '3',
                '--dry-run',
                '--skip-images',
                '--audit-dir',
                str(Path(tmpdir) / 'audit'),
                '--public-dir',
                str(Path(tmpdir) / 'public'),
                stdout=StringIO(),
            )

        run = CurationRun.objects.latest('id')
        context = run.observer_context_json

        # sinal real de build_observer_context(), não o dict estático antigo.
        self.assertEqual(context['marketplace_counts'], {'mercadolivre': 1})
        self.assertEqual(context['editorial_label_counts'], {'cupom': 1, 'desconto_50': 1})
        self.assertEqual(context['messages_analyzed'], 1)
        self.assertIn('lookback_hours', context)

        # metadados do comando (existiam antes desta tarefa) continuam presentes.
        self.assertEqual(context['source'], 'prepare_ai_curation_batch_command')
        self.assertTrue(context['skip_images'])
        self.assertFalse(context['real_send_enabled'])

        # LGPD: nunca dado bruto/sensível no contexto persistido.
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn('999@g.us', serialized)
        self.assertNotIn('hash-sender-secreto', serialized)
        self.assertNotIn('example.com', serialized)
        self.assertNotIn('Texto bruto', serialized)

    def test_market_radar_is_neutral_and_present_in_payload_when_shopee_affiliate_disabled(self):
        """Sprint 6 / Tarefa 6.1 (achado P7): com SHOPEE_AFFILIATE_ENABLED
        desligado (estado real de produção hoje), o payload da IA ainda tem o
        campo `market_radar`, mas vazio/neutro — o radar não tentou chamar a
        API Shopee e não deve mudar nada em relação a hoje.
        """
        with TemporaryDirectory() as tmpdir:
            call_command(
                'prepare_ai_curation_batch',
                '--channel',
                'whatsapp_main',
                '--mode',
                'dry_run',
                '--candidate-limit',
                '3',
                '--dry-run',
                '--skip-images',
                '--audit-dir',
                str(Path(tmpdir) / 'audit'),
                '--public-dir',
                str(Path(tmpdir) / 'public'),
                stdout=StringIO(),
            )

            run = CurationRun.objects.latest('id')
            input_payload = json.loads(Path(run.input_json_path).read_text(encoding='utf-8'))

        self.assertIn('market_radar', input_payload)
        self.assertFalse(input_payload['market_radar']['enabled'])
        self.assertEqual(input_payload['market_radar']['category_scores'], {})
        for offer in input_payload['offers']:
            self.assertNotIn('market_radar_bonus', offer['baseline']['multipliers'])

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

    def test_real_runner_flag_uses_hermes_profile_and_persists_metadata_without_sending(self):
        class RecordingRunner:
            instances = []

            def __init__(self, *, profile_name, timeout_seconds=180, model_override=None, provider_override=None):
                self.profile_name = profile_name
                self.timeout_seconds = timeout_seconds
                self.model_override = model_override
                self.provider_override = provider_override
                self.payloads = []
                self.instances.append(self)

            def run(self, payload):
                self.payloads.append(payload)
                decisions = []
                actual_distribution = {}
                for index, offer in enumerate(payload['offers'], start=1):
                    actual_distribution[offer['marketplace_code']] = actual_distribution.get(offer['marketplace_code'], 0) + 1
                    decisions.append(
                        {
                            'offer_id': offer['offer_id'],
                            'marketplace_code': offer['marketplace_code'],
                            'classification': 'approved',
                            'selected_for_batch': True,
                            'batch_position': index,
                            'conversion_score': 90,
                            'relevance_score': 90,
                            'discount_quality_score': 90,
                            'audience_fit_score': 90,
                            'reason': 'Oferta validada pelo runner real simulado.',
                            'rewritten_title': offer['title'],
                            'rewritten_caption_whatsapp': 'Caption WhatsApp',
                            'rewritten_caption_telegram': 'Caption Telegram',
                            'image_required': False,
                            'image_decision': 'skip',
                            'blacklist_actions': [],
                            'risk_flags': [],
                        }
                    )
                return {'schema_version': '1.0', 'decisions': decisions, 'actual_distribution': actual_distribution}

        with TemporaryDirectory() as tmpdir:
            out = StringIO()
            with patch(
                'apps.curation.management.commands.prepare_ai_curation_batch.HermesProfileRunner',
                RecordingRunner,
            ):
                call_command(
                    'prepare_ai_curation_batch',
                    '--channel',
                    'whatsapp_main',
                    '--runner',
                    'real',
                    '--profile',
                    'descontos-bot',
                    '--candidate-limit',
                    '2',
                    '--dry-run',
                    '--skip-images',
                    '--audit-dir',
                    str(Path(tmpdir) / 'audit'),
                    '--public-dir',
                    str(Path(tmpdir) / 'public'),
                    stdout=out,
                )

        run = CurationRun.objects.latest('id')
        self.assertEqual(run.profile_name, 'descontos-bot')
        self.assertEqual(run.model_provider, 'openai-codex')
        self.assertEqual(run.model_name, 'gpt-5.5')
        self.assertEqual(run.status, CurationRun.Status.COMPLETED)
        self.assertEqual(Delivery.objects.count(), 0)
        self.assertEqual(RecordingRunner.instances[0].profile_name, 'descontos-bot')
        self.assertIsNone(RecordingRunner.instances[0].model_override)
        self.assertIn('runner=real', out.getvalue())

    def test_model_override_passes_to_runner_and_records_metadata(self):
        class RecordingRunner:
            instances = []

            def __init__(self, *, profile_name, timeout_seconds=180, model_override=None, provider_override=None):
                self.profile_name = profile_name
                self.model_override = model_override
                self.provider_override = provider_override
                self.instances.append(self)

            def run(self, payload):
                decisions = []
                actual_distribution = {}
                for index, offer in enumerate(payload['offers'], start=1):
                    actual_distribution[offer['marketplace_code']] = actual_distribution.get(offer['marketplace_code'], 0) + 1
                    decisions.append(
                        {
                            'offer_id': offer['offer_id'],
                            'marketplace_code': offer['marketplace_code'],
                            'classification': 'approved',
                            'selected_for_batch': True,
                            'batch_position': index,
                            'conversion_score': 90,
                            'relevance_score': 90,
                            'discount_quality_score': 90,
                            'audience_fit_score': 90,
                            'reason': 'Oferta validada pelo runner de fallback simulado.',
                            'rewritten_title': offer['title'],
                            'rewritten_caption_whatsapp': 'Caption WhatsApp',
                            'rewritten_caption_telegram': 'Caption Telegram',
                            'image_required': False,
                            'image_decision': 'skip',
                            'blacklist_actions': [],
                            'risk_flags': [],
                        }
                    )
                return {'schema_version': '1.0', 'decisions': decisions, 'actual_distribution': actual_distribution}

        with TemporaryDirectory() as tmpdir:
            with patch(
                'apps.curation.management.commands.prepare_ai_curation_batch.HermesProfileRunner',
                RecordingRunner,
            ):
                call_command(
                    'prepare_ai_curation_batch',
                    '--channel',
                    'whatsapp_main',
                    '--runner',
                    'real',
                    '--profile',
                    'descontos-bot',
                    '--model',
                    'glm-5.2',
                    '--provider',
                    'zai',
                    '--candidate-limit',
                    '2',
                    '--dry-run',
                    '--skip-images',
                    '--audit-dir',
                    str(Path(tmpdir) / 'audit'),
                    '--public-dir',
                    str(Path(tmpdir) / 'public'),
                    stdout=StringIO(),
                )

        runner = RecordingRunner.instances[0]
        self.assertEqual(runner.profile_name, 'descontos-bot')
        self.assertEqual(runner.model_override, 'glm-5.2')
        self.assertEqual(runner.provider_override, 'zai')
        run = CurationRun.objects.latest('id')
        self.assertEqual(run.profile_name, 'descontos-bot')
        self.assertEqual(run.model_name, 'glm-5.2')
        self.assertEqual(run.model_provider, 'zai')

    def test_candidate_selection_balances_shopee_into_agent_payload(self):
        Offer.objects.all().delete()
        now = timezone.now()
        offer_id = 1
        for marketplace_code in ('mercadolivre', 'amazon'):
            for index in range(9):
                Offer.objects.create(
                    marketplace=self.marketplaces[marketplace_code],
                    external_id=f'{marketplace_code}-balanced-{index}',
                    title=f'Oferta forte {marketplace_code} {index}',
                    normalized_title=f'oferta forte {marketplace_code} {index}',
                    offer_hash=f'hash-balanced-{offer_id}',
                    slug=f'oferta-forte-{marketplace_code}-{index}',
                    current_price=Decimal('99.90'),
                    original_price=Decimal('999.00'),
                    discount_pct=Decimal('90.00'),
                    product_url='https://example.com/produto',
                    affiliate_url='https://example.com/afiliado',
                    image_url='https://example.com/img.jpg',
                    is_active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    price_collected_at=now,
                )
                offer_id += 1
        for index in range(4):
            Offer.objects.create(
                marketplace=self.marketplaces['shopee'],
                external_id=f'shopee-balanced-{index}',
                title=f'Oferta Shopee segura {index}',
                normalized_title=f'oferta shopee segura {index}',
                offer_hash=f'hash-balanced-{offer_id}',
                slug=f'oferta-shopee-segura-{index}',
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
            offer_id += 1

        class RecordingRunner:
            payloads = []

            def __init__(self, *args, **kwargs):
                pass

            def run(self, payload):
                self.payloads.append(payload)
                decisions = []
                for index, offer in enumerate(payload['offers'], start=1):
                    decisions.append(
                        {
                            'offer_id': offer['offer_id'],
                            'marketplace_code': offer['marketplace_code'],
                            'classification': 'approved',
                            'selected_for_batch': True,
                            'batch_position': index,
                            'conversion_score': 90,
                            'relevance_score': 90,
                            'discount_quality_score': 90,
                            'audience_fit_score': 90,
                            'reason': 'Oferta validada.',
                            'rewritten_title': offer['title'],
                            'rewritten_caption_whatsapp': 'Caption WhatsApp',
                            'rewritten_caption_telegram': 'Caption Telegram',
                            'image_required': False,
                            'image_decision': 'skip',
                            'blacklist_actions': [],
                            'risk_flags': [],
                        }
                    )
                return {'schema_version': '1.0', 'decisions': decisions, 'actual_distribution': {}}

        with TemporaryDirectory() as tmpdir:
            with patch(
                'apps.curation.management.commands.prepare_ai_curation_batch.HermesProfileRunner',
                RecordingRunner,
            ):
                call_command(
                    'prepare_ai_curation_batch',
                    '--channel',
                    'whatsapp_main',
                    '--runner',
                    'real',
                    '--candidate-limit',
                    '10',
                    '--dry-run',
                    '--skip-images',
                    '--audit-dir',
                    str(Path(tmpdir) / 'audit'),
                    '--public-dir',
                    str(Path(tmpdir) / 'public'),
                    stdout=StringIO(),
                )

        marketplace_codes = [offer['marketplace_code'] for offer in RecordingRunner.payloads[0]['offers']]
        # Sprint 6 / Tarefa 6.4: DEFAULT_TARGET_DISTRIBUTION reponderada por
        # receita real (ml=0.55/amazon=0.35/shopee=0.10, era 0.4/0.3/0.3) —
        # a cota justa da Shopee em candidate_limit=10 caiu de 3 para 1. O
        # ponto do teste (Shopee não fica de fora só por ter desconto menor
        # que ML/Amazon) continua válido com o novo número.
        self.assertEqual(marketplace_codes.count('shopee'), 1)

    def test_balanced_candidate_selection_fills_shortage_from_available_marketplaces(self):
        Offer.objects.all().delete()
        now = timezone.now()
        offer_id = 1
        for marketplace_code, total in (('mercadolivre', 8), ('amazon', 8), ('shopee', 1)):
            for index in range(total):
                Offer.objects.create(
                    marketplace=self.marketplaces[marketplace_code],
                    external_id=f'{marketplace_code}-shortage-{index}',
                    title=f'Oferta shortage {marketplace_code} {index}',
                    normalized_title=f'oferta shortage {marketplace_code} {index}',
                    offer_hash=f'hash-shortage-{offer_id}',
                    slug=f'oferta-shortage-{marketplace_code}-{index}',
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
                offer_id += 1

        selected = _balanced_marketplace_candidates(
            Offer.objects.select_related('marketplace').order_by('-discount_pct', '-current_price', 'title'),
            limit=10,
        )

        marketplace_codes = [offer.marketplace.code for offer in selected]
        self.assertEqual(len(selected), 10)
        self.assertEqual(marketplace_codes.count('shopee'), 1)
        self.assertEqual(marketplace_codes.count('mercadolivre') + marketplace_codes.count('amazon'), 9)

    def test_candidate_pool_skips_obvious_canonical_duplicate_and_fills_from_next_best(self):
        # Sprint 5 / achado P8: o pool de candidatas não deve gastar cota de
        # marketplace com duas ofertas do mesmo produto_canonico_id quando há
        # outra oferta distinta disponível para preencher a cota.
        Offer.objects.all().delete()
        now = timezone.now()
        offer_id = 1

        def _make_ml_offer(index, discount_pct, canonico=''):
            nonlocal offer_id
            offer = Offer.objects.create(
                marketplace=self.marketplaces['mercadolivre'],
                external_id=f'ml-canon-{index}',
                title=f'Oferta ML canon {index}',
                normalized_title=f'oferta ml canon {index}',
                offer_hash=f'hash-canon-{offer_id}',
                slug=f'oferta-ml-canon-{index}',
                produto_canonico_id=canonico,
                current_price=Decimal('99.90'),
                original_price=Decimal('199.80'),
                discount_pct=Decimal(discount_pct),
                product_url='https://example.com/produto',
                affiliate_url='https://example.com/afiliado',
                image_url='https://example.com/img.jpg',
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
                price_collected_at=now,
            )
            offer_id += 1
            return offer

        # Duas primeiras (melhor desconto) são o mesmo produto canônico —
        # a segunda deveria ser descartada do pool em favor de uma das
        # próximas (distintas) para não desperdiçar a cota do ML.
        best = _make_ml_offer(0, '95.00', canonico='mercadolivre:MLBSAME')
        duplicate = _make_ml_offer(1, '90.00', canonico='mercadolivre:MLBSAME')
        distinct_offers = [_make_ml_offer(i, str(80 - i * 5), canonico='') for i in range(2, 6)]

        for marketplace_code in ('amazon', 'shopee'):
            for index in range(5):
                Offer.objects.create(
                    marketplace=self.marketplaces[marketplace_code],
                    external_id=f'{marketplace_code}-canon-{index}',
                    title=f'Oferta {marketplace_code} canon {index}',
                    normalized_title=f'oferta {marketplace_code} canon {index}',
                    offer_hash=f'hash-canon-{offer_id}',
                    slug=f'oferta-{marketplace_code}-canon-{index}',
                    current_price=Decimal('99.90'),
                    original_price=Decimal('199.80'),
                    discount_pct=Decimal('70.00'),
                    product_url='https://example.com/produto',
                    affiliate_url='https://example.com/afiliado',
                    image_url='https://example.com/img.jpg',
                    is_active=True,
                    first_seen_at=now,
                    last_seen_at=now,
                    price_collected_at=now,
                )
                offer_id += 1

        selected = _balanced_marketplace_candidates(
            Offer.objects.select_related('marketplace').order_by('-discount_pct', '-current_price', 'title'),
            limit=10,
        )

        selected_ids = {offer.id for offer in selected}
        ml_canonicos = [offer.produto_canonico_id for offer in selected if offer.marketplace.code == 'mercadolivre']

        self.assertEqual(len(selected), 10)
        self.assertIn(best.id, selected_ids)
        self.assertNotIn(duplicate.id, selected_ids)
        # A cota do ML é 5 (Sprint 6 / Tarefa 6.4: DEFAULT_TARGET_DISTRIBUTION
        # ml=0.55, era 0.4): best + os 4 melhores distintos preenchem a cota
        # (a duplicata é que sobrou de fora).
        self.assertIn(distinct_offers[0].id, selected_ids)
        self.assertEqual(ml_canonicos.count('mercadolivre:MLBSAME'), 1)
