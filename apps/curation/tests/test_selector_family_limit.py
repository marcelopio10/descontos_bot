from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.selector import SelectionConfig, select_offers_for_channel
from apps.curation.services.product_family import product_family_key
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting


class SelectorFamilyLimitTests(TestCase):
    """Achado 2026-08-21: o selector legado publicava sem gate de família.

    Os gates de diversidade nasceram dentro do fluxo de curadoria IA, e este
    selector é o **fallback** de quando a IA falha — ou seja, roda justamente
    quando algo já deu errado. No dia da medição, 17 dos 25 envios saíram por
    aqui, entre eles 7 fones de ouvido em 3 minutos.
    """

    FONES = [
        'PHILIPS, Fone de Ouvido com Microfone, TAUE101WT/00, Com fio',
        'FONE DE OUVIDO PHILIPS TWS TAT1139BK Bluetooth',
        'JBL, Fone de Ouvido Bluetooth Over-Ear, Tune 530BT, Sem Fio',
    ]

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
        self.config = SelectionConfig(
            global_limit=20,
            marketplace_limit=20,
            min_discount_percentage=Decimal('20'),
            min_quality_score=0.0,
            priority_quality_score=1000.0,
            exposure_quota_enabled=False,
        )

    def _offer(self, title: str, preco: str = '75.00') -> Offer:
        agora = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=title[:40],
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{Offer.objects.count()}-{title[:10]}',
            slug=f'oferta-{Offer.objects.count()}',
            current_price=Decimal(preco),
            original_price=Decimal('140.00'),
            discount_pct=Decimal('50.00'),
            product_url=f'https://example.com/{title[:20]}',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=agora,
            last_seen_at=agora,
            price_collected_at=agora,
        )

    def test_nao_seleciona_varios_do_mesmo_tipo_de_produto(self):
        for titulo in self.FONES:
            self._offer(titulo)
        self.assertEqual(
            {product_family_key(t) for t in self.FONES},
            {'fone_de_ouvido'},
            'fixture precisa cair na mesma família para o teste ter sentido',
        )

        selecionadas = select_offers_for_channel(self.channel, self.config)

        familias = [product_family_key(o.title) for o in selecionadas]
        self.assertEqual(familias.count('fone_de_ouvido'), 1)

    def test_produtos_de_familias_diferentes_passam_juntos(self):
        self._offer('PHILIPS, Fone de Ouvido com Microfone, TAUE101WT/00, Com fio')
        self._offer('Tênis Olympikus Corre Trilha 2 Masculino', preco='338.00')
        self._offer('Jogo de Panelas Antiaderente Mondial 5 Peças', preco='199.00')

        selecionadas = select_offers_for_channel(self.channel, self.config)

        self.assertEqual(len(selecionadas), 3)

    def test_flag_desligada_devolve_o_comportamento_anterior(self):
        """`offer_family_spacing_enabled=false` desarma o espaçamento por histórico.

        O teto dentro da seleção continua valendo: ele é o equivalente ao
        `max_per_family` do lote, não ao espaçamento no tempo.
        """
        Setting.objects.create(key='offer_family_spacing_enabled', value='false')
        for titulo in self.FONES:
            self._offer(titulo)

        selecionadas = select_offers_for_channel(self.channel, self.config)

        familias = [product_family_key(o.title) for o in selecionadas]
        self.assertEqual(familias.count('fone_de_ouvido'), 1)
