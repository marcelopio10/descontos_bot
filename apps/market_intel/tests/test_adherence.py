from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.distribution.models import Delivery, SocialChannel
from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.market_intel.services.adherence import build_adherence
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class AdherenceTests(TestCase):
    def setUp(self):
        self.canal = SocialChannel.objects.create(
            name='WhatsApp principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='descontos.bot',
        )
        self.marketplace = Marketplace.objects.create(code='mercadolivre', name='Mercado Livre')
        self.grupos = [
            ObservedWhatsAppGroup.objects.create(name=f'Grupo {i}', jid=f'{i}@g.us')
            for i in range(4)
        ]
        # O nosso próprio canal também é grupo observado; não pode contar como eco.
        self.nosso = ObservedWhatsAppGroup.objects.create(name='descontos.bot', jid='9@g.us')

    def _observa(self, grupo, texto, preco, horas_atras=5):
        instante = timezone.now() - timedelta(hours=horas_atras)
        return ObservedWhatsAppMessage.objects.create(
            group=grupo,
            external_message_id=f'{grupo.id}-{texto[:12]}-{horas_atras}',
            sender_hash='a' * 64,
            sent_at=instante,
            collected_at=instante,
            text=texto,
            urls=['https://meli.la/x'],
            parsed_marketplace='mercadolivre',
            parsed_price=Decimal(str(preco)),
        )

    def _envia(self, titulo, preco, horas_atras=1, origem='competitor_radar'):
        agora = timezone.now()
        oferta = Offer.objects.create(
            marketplace=self.marketplace,
            external_id=f'MLB-{titulo[:10]}-{preco}',
            title=titulo,
            normalized_title=titulo.lower(),
            offer_hash=f'hash-{titulo[:10]}-{preco}',
            current_price=Decimal(str(preco)),
            product_url=f'https://www.mercadolivre.com.br/{titulo[:8]}',
            first_seen_at=agora,
            last_seen_at=agora,
            raw_payload={'search_provenance': {'source_kind': origem}},
        )
        return Delivery.objects.create(
            offer=oferta,
            social_channel=self.canal,
            message='...',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=agora - timedelta(hours=horas_atras),
        )

    def test_envio_com_eco_nos_grupos(self):
        self._observa(self.grupos[0], '*Camiseta Light T-shirt Insider*', 56, horas_atras=5)
        self._envia('Camiseta Light T-shirt Insider Masculina', 56)

        relatorio = build_adherence(days=7)

        self.assertEqual(relatorio.envios, 1)
        self.assertEqual(relatorio.envios_com_eco, 1)
        self.assertEqual(relatorio.taxa_eco, 100.0)

    def test_envio_que_ninguem_mais_publicou_conta_como_exclusivo(self):
        self._observa(self.grupos[0], '*Camiseta Light T-shirt Insider*', 56)
        self._envia('Cartão De Memória 128gb Micro Sd Para Câmeras', 23, origem='generic_fallback')

        relatorio = build_adherence(days=7)

        self.assertEqual(relatorio.envios_exclusivos, 1)
        self.assertEqual(relatorio.envios_com_eco, 0)
        self.assertEqual(relatorio.exclusivos[0]['origem'], 'generic_fallback')

    def test_mesmo_tipo_em_faixa_de_preco_diferente_conta_so_no_teto(self):
        """Eles anunciam com cupom e nós o preço de página — a faixa diverge."""
        self._observa(self.grupos[0], '*Camiseta Light T-shirt Insider*', 56)
        self._envia('Camiseta Light T-shirt Insider Masculina', 69)

        relatorio = build_adherence(days=7)

        self.assertEqual(relatorio.taxa_eco, 0.0)
        self.assertEqual(relatorio.taxa_eco_de_familia, 100.0)

    def test_nosso_proprio_grupo_nao_conta_como_eco(self):
        self._observa(self.nosso, '*Camiseta Light T-shirt Insider*', 56)
        self._envia('Camiseta Light T-shirt Insider Masculina', 56)

        self.assertEqual(build_adherence(days=7).envios_com_eco, 0)

    def test_cobertura_do_consenso_forte(self):
        for grupo in self.grupos[:3]:
            self._observa(grupo, '*Kit 10 Cuecas Boxer Mash Algodão*', 79)
        for grupo in self.grupos[:3]:
            self._observa(grupo, '*Tênis Olympikus Corre Trilha 2*', 338)
        self._envia('Kit 10 Cuecas Boxer Mash Algodão Masculina', 79)

        relatorio = build_adherence(days=7)

        self.assertEqual(relatorio.ofertas_consenso_forte, 2)
        self.assertEqual(relatorio.consenso_forte_publicado, 1)
        self.assertEqual(relatorio.taxa_cobertura_consenso, 50.0)
        self.assertEqual(relatorio.lacunas[0]['familia'], 'tenis')
        self.assertEqual(relatorio.lacunas[0]['grupos'], 3)

    def test_oferta_de_um_grupo_so_nao_vira_lacuna(self):
        self._observa(self.grupos[0], '*Tênis Olympikus Corre Trilha 2*', 338)

        relatorio = build_adherence(days=7)

        self.assertEqual(relatorio.ofertas_consenso_forte, 0)
        self.assertEqual(relatorio.lacunas, [])

    def test_taxa_de_eco_por_origem_da_coleta(self):
        self._observa(self.grupos[0], '*Kit 10 Cuecas Boxer Mash Algodão*', 79)
        self._envia('Kit 10 Cuecas Boxer Mash Algodão Masculina', 79, origem='competitor_radar')
        self._envia('Cartão De Memória 128gb Micro Sd', 23, origem='generic_fallback')

        por_origem = build_adherence(days=7).por_origem

        self.assertEqual(por_origem['competitor_radar']['taxa_de_eco_pct'], 100.0)
        self.assertEqual(por_origem['generic_fallback']['taxa_de_eco_pct'], 0.0)
