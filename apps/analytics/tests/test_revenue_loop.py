"""Cobertura do relatório publicado × vendido (item 7 da Onda 1, 2026-08-23).

O que estes testes protegem, em ordem de importância:

1. **A faixa de preço sair do preço publicado, não do preço de hoje.** Se o
   relatório usar `Offer.current_price`, uma oferta que mudou de preço depois do
   envio migra de faixa retroativamente — e a faixa é justamente o recorte que
   deveria ter pego o corte dos R$ 500 em uma semana.
2. **Compra própria não contaminar receita.** É o mesmo risco da ingestão: com
   ela dentro, o relatório mente a favor.
3. **A separação dos dois caminhos de publicação** (curadoria IA × selector
   legado), que é o número em que a decisão do item 9 se apoia.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import (
    AffiliateImportBatch,
    AffiliateSource,
    MLAffiliateSale,
    OwnPurchaseSource,
)
from apps.analytics.services.revenue_loop import build_revenue_loop_report
from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Category, Offer, PriceHistoryEntry


class RevenueLoopTestCase(TestCase):
    def setUp(self):
        # Categorias, marketplaces e canais chegam por migration de dados —
        # criar de novo estoura a unique de `code`.
        self.marketplace, _ = Marketplace.objects.get_or_create(
            code='mercadolivre',
            defaults={'name': 'Mercado Livre'},
        )
        self.category, _ = Category.objects.get_or_create(
            code='beleza_cuidados',
            defaults={'name': 'Beleza e Cuidados'},
        )
        self.channel, _ = SocialChannel.objects.get_or_create(
            code='whatsapp_principal',
            defaults={
                'name': 'WhatsApp principal',
                'channel_type': 'whatsapp',
                'target': 'grupo',
            },
        )
        self.batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.MERCADO_LIVRE,
            period_start=timezone.localdate() - timedelta(days=30),
            period_end=timezone.localdate(),
            raw_filename='teste.json',
            payload_sha256='hash-teste',
        )

    def _offer(self, external_id: str, price: str, title: str = 'Perfume Importado 100ml') -> Offer:
        return Offer.objects.create(
            marketplace=self.marketplace,
            category=self.category,
            external_id=external_id,
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{external_id}',
            current_price=Decimal(price),
            product_url=f'https://mercadolivre.com.br/{external_id}',
            first_seen_at=timezone.now() - timedelta(days=30),
            last_seen_at=timezone.now(),
        )

    def _delivery(self, offer: Offer, days_ago: int = 3) -> Delivery:
        return Delivery.objects.create(
            offer=offer,
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=timezone.now() - timedelta(days=days_ago),
        )

    def _sale(self, offer=None, value='600', commission='90', days_ago: int = 3, **overrides):
        defaults = {
            'batch': self.batch,
            'offer': offer,
            'sale_id': overrides.pop('sale_id', f'venda-{MLAffiliateSale.objects.count() + 1}'),
            'sale_date': (timezone.now() - timedelta(days=days_ago)).date(),
            'product_title': 'Perfume Importado 100ml',
            'sale_value_brl': Decimal(value),
            'commission_brl': Decimal(commission),
            'status': 'IN_REVIEW',
        }
        defaults.update(overrides)
        return MLAffiliateSale.objects.create(**defaults)


class PriceBandTests(RevenueLoopTestCase):
    def test_faixa_usa_o_preco_da_publicacao_e_nao_o_de_hoje(self):
        """Oferta publicada a R$ 700 e hoje a R$ 90 pertence à faixa de 500 a
        1.000 — senão o relatório reescreve o passado."""
        offer = self._offer('MLB1', '90')
        delivery = self._delivery(offer, days_ago=3)
        PriceHistoryEntry.objects.create(
            offer=offer,
            price=Decimal('700'),
            collected_at=delivery.sent_at - timedelta(hours=1),
        )
        PriceHistoryEntry.objects.create(
            offer=offer,
            price=Decimal('90'),
            collected_at=timezone.now(),
        )

        report = build_revenue_loop_report(weeks=4)

        faixas = {row.label: row.deliveries for row in report.bands}
        self.assertEqual(faixas['R$ 500 a 1.000'], 1)
        self.assertEqual(faixas['até R$ 100'], 0)

    def test_sem_historico_anterior_cai_no_preco_atual(self):
        """Oferta coletada e publicada no mesmo ciclo não tem ponto anterior."""
        offer = self._offer('MLB2', '250')
        self._delivery(offer)

        report = build_revenue_loop_report(weeks=4)

        faixas = {row.label: row.deliveries for row in report.bands}
        self.assertEqual(faixas['R$ 100 a 300'], 1)

    def test_comissao_por_mil_envios_por_faixa(self):
        # `Delivery` tem unique (oferta, canal): duas publicações na mesma faixa
        # são duas ofertas, não a mesma publicada duas vezes.
        offer = self._offer('MLB3', '600')
        outra = self._offer('MLB3B', '700')
        for alvo in (offer, outra):
            self._delivery(alvo)
        self._sale(offer=offer, value='600', commission='90')

        report = build_revenue_loop_report(weeks=4)

        faixa = next(row for row in report.bands if row.label == 'R$ 500 a 1.000')
        self.assertEqual(faixa.deliveries, 2)
        self.assertEqual(faixa.sales, 1)
        self.assertEqual(faixa.commission, Decimal('90'))
        self.assertEqual(faixa.commission_per_thousand, Decimal('45000.00'))


class OwnPurchaseTests(RevenueLoopTestCase):
    def test_compra_propria_fica_fora_de_todo_calculo(self):
        offer = self._offer('MLB4', '600')
        self._delivery(offer)
        self._sale(offer=offer, commission='90')
        self._sale(
            offer=offer,
            commission='500',
            sale_id='venda-propria',
            is_own_purchase=True,
            own_purchase_source=OwnPurchaseSource.AUTO_REJECTED,
            status='REJECTED',
        )

        report = build_revenue_loop_report(weeks=4)

        self.assertEqual(report.sales_total, 1)
        self.assertEqual(report.commission_total, Decimal('90'))
        self.assertEqual(report.own_purchases_excluded, 1)
        self.assertTrue(
            any('compra própria' in w for w in report.warnings),
            report.warnings,
        )


class PublicationPathTests(RevenueLoopTestCase):
    def _curated_delivery(self, offer: Offer) -> Delivery:
        delivery = self._delivery(offer)
        run = CurationRun.objects.create(channel=self.channel, status='succeeded', mode='ai')
        batch = CuratedBatch.objects.create(run=run, channel=self.channel, batch_size=1)
        decision = CurationDecision.objects.create(
            run=run,
            offer=offer,
            ai_classification=CurationDecision.Classification.APPROVED,
            is_selected_for_batch=True,
        )
        CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=offer,
            position=1,
            final_title=offer.title,
            delivery=delivery,
        )
        return delivery

    def test_separa_curadoria_ia_de_selector_legado(self):
        """Entrega sem `CuratedBatchItem` é do selector legado — é o fallback que
        roda justamente quando a IA falha, e ele precisa ser visível."""
        self._curated_delivery(self._offer('MLB5', '200'))
        self._delivery(self._offer('MLB6', '200'))
        self._delivery(self._offer('MLB7', '200'))

        report = build_revenue_loop_report(weeks=4)

        caminhos = {row.code: row for row in report.paths}
        self.assertEqual(caminhos['curadoria_ia'].deliveries, 1)
        self.assertEqual(caminhos['selector_legado'].deliveries, 2)
        self.assertEqual(caminhos['selector_legado'].deliveries_pct, 66.7)
        self.assertTrue(
            any('selector legado' in w for w in report.warnings),
            report.warnings,
        )


class MaturityWarningTests(RevenueLoopTestCase):
    def test_avisa_quando_a_janela_esta_majoritariamente_em_revisao(self):
        """Sem este aviso, uma janela recente parece queda de receita quando é
        só status não resolvido."""
        offer = self._offer('MLB8', '200')
        self._delivery(offer)
        self._sale(offer=offer, commission='30', status='IN_REVIEW')
        self._sale(offer=offer, commission='20', sale_id='venda-aprovada', status='APPROVED')

        report = build_revenue_loop_report(weeks=4)

        self.assertEqual(report.commission_in_review, Decimal('30'))
        self.assertEqual(report.commission_approved, Decimal('20'))
        self.assertTrue(
            any('IN_REVIEW' in w for w in report.warnings),
            report.warnings,
        )


class GapTests(RevenueLoopTestCase):
    def test_lista_familia_que_vendeu_e_nao_publicamos(self):
        """O padrão do caso Insider: vendeu, paramos de cobrir, ninguém viu."""
        publicada = self._offer('MLB9', '200', title='Camiseta Básica Algodão')
        self._delivery(publicada)
        self._sale(
            offer=None,
            commission='40',
            product_title='Tênis Corrida Masculino Leve',
        )

        report = build_revenue_loop_report(weeks=4)

        familias = {row.family for row in report.gaps}
        self.assertTrue(familias, 'esperava ao menos uma lacuna')
        self.assertNotIn('camiseta', familias)
