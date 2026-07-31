from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.blacklist import get_blacklist_terms, is_blacklisted
from apps.curation.services.selector import SelectionConfig, select_offers_for_channel
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting


class SafetyBlacklistTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )

    def _offer(self, title: str, discount: Decimal = Decimal('50.00')) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=title[:40],
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{Offer.objects.count()}-{title[:10]}',
            slug=f'oferta-{Offer.objects.count()}',
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=discount,
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_safety_terms_are_enforced_even_when_panel_overrides_blacklist(self):
        Setting.objects.create(key='blacklist_terms', value='["usado"]')

        terms = get_blacklist_terms()

        self.assertIn('usado', terms)
        self.assertIn('super cavalo', terms)
        self.assertIn('torofila', terms)
        self.assertIn('vibrador sexual', terms)
        self.assertNotIn('vibrador', terms)
        self.assertIn('sensual', terms)
        self.assertIn('lingerie', terms)

    def test_adult_supplement_title_is_blacklisted(self):
        offer = self._offer('Aumenta Super Cavalo Torofila Feno Grego 60 Cápsulas Potente Sem Sabor')

        self.assertTrue(is_blacklisted(offer))

    def test_tadal_male_enhancement_title_is_blacklisted(self):
        offer = self._offer(
            'Suplemento Masculino Fila Aumenta Tamanho Natural Tadala 60 Sem Sabor',
        )

        self.assertTrue(is_blacklisted(offer))

    def test_prank_bodily_function_title_is_blacklisted(self):
        offer = self._offer(
            'Peido Alemão Peido Pronto Pum Pegadinha Super Forte Zoeira Pegadinha 30ml',
        )

        self.assertTrue(is_blacklisted(offer))

    def test_editorially_irrelevant_training_head_title_is_blacklisted(self):
        offer = self._offer(
            'Cabeça P/ Treino Com Barba Lisa Masculina 100% Natural C Suporte Cor Castanho Zhang Hair',
        )

        self.assertTrue(is_blacklisted(offer))

    def test_selector_never_returns_adult_safety_blacklisted_offer(self):
        blocked = self._offer('Aumenta Super Cavalo Torofila Feno Grego 60 Cápsulas Potente Sem Sabor')
        allowed = self._offer('Tênis Adidas Runfalcon 5 Corrida De Rua Macio Masculino', Decimal('30.00'))
        Setting.objects.create(key='blacklist_terms', value='["usado"]')
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(allowed, selected)
        self.assertNotIn(blocked, selected)

    def test_selector_never_returns_tadal_male_enhancement_offer(self):
        blocked = self._offer(
            'Suplemento Masculino Fila Aumenta Tamanho Natural Tadala 60 Sem Sabor',
        )
        allowed = self._offer('Tênis Adidas Runfalcon 5 Corrida De Rua Macio Masculino', Decimal('30.00'))
        Setting.objects.create(key='blacklist_terms', value='[]')
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(allowed, selected)
        self.assertNotIn(blocked, selected)

    def test_selector_never_returns_editorially_irrelevant_training_head(self):
        blocked = self._offer(
            'Cabeça P/ Treino Com Barba Lisa Masculina 100% Natural C Suporte Cor Castanho Zhang Hair',
        )
        allowed = self._offer('Tênis Adidas Runfalcon 5 Corrida De Rua Macio Masculino', Decimal('30.00'))
        Setting.objects.create(key='blacklist_terms', value='[]')
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(allowed, selected)
        self.assertNotIn(blocked, selected)

    def test_selector_drops_near_duplicate_titles_with_reordered_tokens(self):
        first = self._offer('Camisa Torcedor 1.1 Tailand Masculina Amarela 2026', Decimal('66.00'))
        duplicate = self._offer('Camisa Torcedor Tailand 1.1 Amarela Masculina 2026', Decimal('57.00'))
        allowed = self._offer('Cafeteira Elétrica Inox 30 Xícaras Oferta Especial', Decimal('30.00'))
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertEqual(1, len([offer for offer in selected if offer in {first, duplicate}]))
        self.assertIn(allowed, selected)

    def test_selector_allows_offer_sent_to_a_different_channel(self):
        sent_elsewhere = self._offer('Cafeteira Elétrica Inox 30 Xícaras Oferta Especial')
        other_channel = SocialChannel.objects.create(
            name='Telegram',
            code='telegram_main',
            target='@descontosbot',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        Delivery.objects.create(
            offer=sent_elsewhere,
            social_channel=other_channel,
            message='mensagem enviada anteriormente',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=timezone.now(),
        )
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(sent_elsewhere, selected)

    def test_selector_allows_offer_failed_in_channel_even_if_sent_elsewhere(self):
        retriable = self._offer('Relógio Led Digital Esportivo Promoção Especial')
        other_channel = SocialChannel.objects.create(
            name='Telegram',
            code='telegram_main',
            target='@descontosbot',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        Delivery.objects.create(
            offer=retriable,
            social_channel=other_channel,
            message='mensagem enviada no telegram',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=timezone.now(),
        )
        Delivery.objects.create(
            offer=retriable,
            social_channel=self.channel,
            message='falha anterior no whatsapp',
            delivery_status=Delivery.DeliveryStatus.FAILED,
        )
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(retriable, selected)

    def _pending_batch_item(self, offer: Offer, channel: SocialChannel, *, expires_at=None) -> CuratedBatchItem:
        run = CurationRun.objects.create(channel=channel, status=CurationRun.Status.COMPLETED)
        batch = CuratedBatch.objects.create(
            run=run,
            channel=channel,
            status=CuratedBatch.Status.READY,
            expires_at=expires_at if expires_at is not None else timezone.now() + timezone.timedelta(hours=24),
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=offer,
            ai_classification=CurationDecision.Classification.APPROVED,
            is_selected_for_batch=True,
        )
        return CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=offer,
            position=1,
            final_title=offer.title,
            send_status=CuratedBatchItem.SendStatus.PENDING,
        )

    def test_selector_excludes_offer_pending_in_active_batch_same_channel(self):
        """Achado 2026-07-22: sem essa exclusão, o mesmo topo do ranking por
        desconto era reselecionado a cada ciclo de preparo enquanto o lote
        anterior ainda não tinha sido consumido, gerando lotes com 80-90% de
        duplicatas descartadas (`skipped`) quando o consumo atrasa.
        """
        queued = self._offer('Fone Bluetooth Esportivo Recarregável Prova D\'água')
        self._pending_batch_item(queued, self.channel)
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertNotIn(queued, selected)

    def test_selector_allows_offer_pending_in_active_batch_of_a_different_channel(self):
        queued_elsewhere = self._offer('Panela de Pressão Elétrica Digital 5 Litros')
        other_channel = SocialChannel.objects.create(
            name='Telegram',
            code='telegram_main',
            target='@descontosbot',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self._pending_batch_item(queued_elsewhere, other_channel)
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(queued_elsewhere, selected)

    def test_selector_allows_offer_pending_in_expired_batch(self):
        expired_hold = self._offer('Cadeira Gamer Ergonômica Reclinável Preta')
        self._pending_batch_item(
            expired_hold,
            self.channel,
            expires_at=timezone.now() - timezone.timedelta(hours=1),
        )
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(expired_hold, selected)
