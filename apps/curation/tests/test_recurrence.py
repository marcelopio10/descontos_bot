from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.recurrence import (
    FAMILY_SPACING_FLAG,
    family_spacing_signal,
    filter_saturated_families,
    recurrence_score_multiplier,
    recurrence_signal,
)
from apps.panel.models import Setting
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.delivery import _should_republish_after_improvement
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class RecurrencePolicyTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp', code='whatsapp_main', target='test',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre',
            base_url='https://mercadolivre.com.br', is_active=True,
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace, external_id='ML-1',
            title='Bicicleta Spinning X11', normalized_title='bicicleta spinning x11',
            offer_hash='recurrence-offer-1', slug='recurrence-offer-1',
            produto_canonico_id='ML-X11', current_price=Decimal('900'),
            original_price=Decimal('1200'), discount_pct=Decimal('25'),
            product_url='https://example.com/product', affiliate_url='https://example.com/affiliate',
            image_url='https://example.com/image.jpg', first_seen_at=now, last_seen_at=now,
            price_collected_at=now,
        )

    def _sent(self, sent_at, *, offer=None, suffix=''):
        offer = offer or self.offer
        return Delivery.objects.create(
            offer=offer, social_channel=self.channel,
            message='Oferta R$ 900,00', delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=sent_at,
        )

    def _same_family_offer(self):
        return Offer.objects.create(
            marketplace=self.marketplace, external_id='ML-2',
            title='Bicicleta Spinning X11 vendedor 2', normalized_title='bicicleta spinning x11 vendedor 2',
            offer_hash='recurrence-offer-2', slug='recurrence-offer-2',
            produto_canonico_id='ML-X11', current_price=Decimal('900'),
            original_price=Decimal('1200'), discount_pct=Decimal('25'),
            product_url='https://example.com/product-2', affiliate_url='https://example.com/affiliate-2',
            image_url='https://example.com/image-2.jpg', first_seen_at=timezone.now(),
            last_seen_at=timezone.now(), price_collected_at=timezone.now(),
        )

    def test_recent_send_is_blocked_by_cooldown(self):
        now = timezone.now()
        self._sent(now - timedelta(hours=24))
        signal = recurrence_signal(self.offer, self.channel, now=now)
        self.assertTrue(signal.blocked)
        self.assertEqual(recurrence_score_multiplier(signal), 0.0)

    def test_saturated_family_is_penalized_after_cooldown(self):
        now = timezone.now()
        self._sent(now - timedelta(days=10))
        second = self._same_family_offer()
        self._sent(now - timedelta(days=8), offer=second)
        signal = recurrence_signal(self.offer, self.channel, now=now)
        self.assertFalse(signal.blocked)
        self.assertTrue(signal.penalized)
        self.assertEqual(recurrence_score_multiplier(signal), 0.72)

    def test_material_price_drop_remains_allowed_after_cooldown(self):
        old = self._sent(timezone.now() - timedelta(days=2))
        changed = Offer.objects.get(pk=self.offer.pk)
        changed.current_price = Decimal('780')
        changed.save(update_fields=['current_price', 'updated_at'])
        self.assertTrue(_should_republish_after_improvement(old, changed, 'Oferta R$ 780,00'))

    def test_failed_delivery_does_not_count_as_recurrence(self):
        Delivery.objects.create(
            offer=self.offer, social_channel=self.channel,
            message='Falhou', delivery_status=Delivery.DeliveryStatus.FAILED,
            sent_at=timezone.now() - timedelta(hours=1),
        )
        signal = recurrence_signal(self.offer, self.channel)
        self.assertEqual(signal.successful_sends, 0)
        self.assertFalse(signal.blocked)


class FamilySpacingTests(TestCase):
    """Achado 2026-08-21: o cooldown antigo era por produto_canonico_id, então
    dois anúncios distintos do mesmo tipo de produto saíam com horas de
    diferença sem nenhum gate ver."""

    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp', code='whatsapp_principal', target='test',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre',
            base_url='https://mercadolivre.com.br', is_active=True,
        )

    def _offer(self, external_id, title):
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace, external_id=external_id,
            title=title, normalized_title=title.lower(),
            offer_hash=f'family-{external_id}', slug=f'family-{external_id}'.lower(),
            produto_canonico_id=f'mercadolivre:{external_id}',
            current_price=Decimal('172'), original_price=Decimal('329'),
            discount_pct=Decimal('47'), product_url=f'https://example.com/{external_id}',
            affiliate_url=f'https://example.com/af/{external_id}',
            image_url='https://example.com/image.jpg',
            first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )

    def _sent(self, offer, sent_at):
        return Delivery.objects.create(
            offer=offer, social_channel=self.channel, message='Oferta',
            delivery_status=Delivery.DeliveryStatus.SENT, sent_at=sent_at,
        )

    def test_bloqueia_tipo_de_produto_repetido_mesmo_com_canonico_diferente(self):
        now = timezone.now()
        enviada = self._offer('MLB_PiscinaRetangularI', 'Piscina Retangular Inflável Pvc Verão Fundo Acolchoado')
        candidata = self._offer('MLB_PiscinaInfantilRet', 'Piscina Infantil Retangular Inflável De Plástico')
        self._sent(enviada, now - timedelta(hours=3))

        self.assertNotEqual(enviada.produto_canonico_id, candidata.produto_canonico_id)
        signal = family_spacing_signal(candidata, self.channel, now=now)
        self.assertTrue(signal.blocked)
        self.assertEqual(signal.reason, 'family_cooldown')
        self.assertEqual(signal.family, 'piscina')

    def test_libera_apos_o_cooldown_da_familia(self):
        now = timezone.now()
        enviada = self._offer('MLB1', 'Power Bank Hardline 20000mAh Turbo')
        candidata = self._offer('MLB2', 'Carregador Portátil Power Bank Turbo 20000mah')
        self._sent(enviada, now - timedelta(hours=9))

        signal = family_spacing_signal(candidata, self.channel, now=now)
        self.assertFalse(signal.blocked)

    def test_satura_a_familia_apos_o_maximo_de_envios_na_janela(self):
        now = timezone.now()
        primeira = self._offer('MLB1', 'Tênis Masculino Grand Court adidas')
        segunda = self._offer('MLB2', 'Tênis Olympikus Only 2 Masculino')
        candidata = self._offer('MLB3', 'Tênis Feminino Response 2 adidas')
        self._sent(primeira, now - timedelta(hours=20))
        self._sent(segunda, now - timedelta(hours=10))

        signal = family_spacing_signal(candidata, self.channel, now=now)
        self.assertTrue(signal.blocked)
        self.assertEqual(signal.reason, 'family_window_saturated')

    def test_nao_bloqueia_tipos_diferentes(self):
        now = timezone.now()
        enviada = self._offer('MLB1', 'Piscina Retangular Inflável Pvc')
        candidata = self._offer('MLB2', 'Power Bank Hardline 20000mAh Turbo')
        self._sent(enviada, now - timedelta(hours=1))

        self.assertFalse(family_spacing_signal(candidata, self.channel, now=now).blocked)

    def test_titulo_sem_familia_nunca_e_bloqueado(self):
        now = timezone.now()
        enviada = self._offer('MLB1', '123 456')
        candidata = self._offer('MLB2', '789 012')
        self._sent(enviada, now - timedelta(minutes=5))

        signal = family_spacing_signal(candidata, self.channel, now=now)
        self.assertFalse(signal.blocked)
        self.assertEqual(signal.family, '')

    def test_flag_desligada_nao_bloqueia_nada(self):
        now = timezone.now()
        Setting.objects.create(key=FAMILY_SPACING_FLAG, value='false')
        enviada = self._offer('MLB1', 'Piscina Retangular Inflável Pvc')
        candidata = self._offer('MLB2', 'Piscina Infantil Retangular Inflável')
        self._sent(enviada, now - timedelta(hours=1))

        self.assertFalse(family_spacing_signal(candidata, self.channel, now=now).blocked)
        self.assertEqual(filter_saturated_families([candidata], self.channel, now=now), [candidata])

    def test_filtro_remove_candidata_saturada_e_mantem_as_demais(self):
        now = timezone.now()
        enviada = self._offer('MLB1', 'Piscina Retangular Inflável Pvc')
        bloqueada = self._offer('MLB2', 'Piscina Infantil Retangular Inflável')
        livre = self._offer('MLB3', 'Jogo De Panelas Cerâmica Antiaderente')
        self._sent(enviada, now - timedelta(hours=2))

        kept = filter_saturated_families([bloqueada, livre], self.channel, now=now)

        self.assertEqual(kept, [livre])
