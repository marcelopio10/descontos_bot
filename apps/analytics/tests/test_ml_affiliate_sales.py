"""Cobertura da ingestão de vendas do painel de afiliados do ML (2026-08-23).

O que estes testes protegem, em ordem de importância:

1. A marcação manual de compra própria **nunca** ser sobrescrita pela rotina
   automática — é o dado que separa receita real de compra da casa, e perdê-lo
   faz todo painel mentir a favor.
2. Idempotência por `sale_id`, sem a qual o timer semanal com janela sobreposta
   multiplicaria a receita a cada execução.
3. O join venda → oferta não casar coisa errada (link de catálogo é outro
   namespace; título só casa acima do limiar).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import MLAffiliateSale, OwnPurchaseSource
from apps.analytics.services.affiliate_parsers.mercadolivre_sales import (
    ingest_ml_sales,
)
from apps.analytics.services.ml_affiliate_sales_client import (
    parse_sales_payload,
)
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


def sale_payload(**overrides) -> dict:
    """Item no formato real do painel, conferido na captura de 2026-08-23."""
    base = {
        'id': '2000017859207054',
        'date': '10/08/2026',
        'link': (
            'https://produto.mercadolivre.com.br/MLB-4452319413-travesseiro-kit-'
            'nasa-x-2-un-duoflex-_JM'
        ),
        'productName': 'Travesseiro Kit Nasa X 2 Un Duoflex Altura 10cm Antiácaro',
        'categoryName': 'Camas, Colchões e Acessórios',
        'storeName': 'BEGTRAVESSEIROS',
        'saleValue': 144,
        'saleUnits': 1,
        'commissionValue': 14.17,
        'commissionPercentage': 12,
        'saleType': 'DIRECT',
        'status': 'IN_REVIEW',
        'statusDetail': '',
    }
    base.update(overrides)
    return base


class ParseSalesPayloadTests(TestCase):
    def test_extrai_vendas_de_envelope_aninhado(self):
        """O envelope do painel já mudou de nome antes; o parser procura pela
        forma do item, não pela chave."""
        payload = {'results': {'data': {'sales': [sale_payload()]}}}

        records = parse_sales_payload(payload)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].sale_id, '2000017859207054')
        self.assertEqual(records[0].sale_date, date(2026, 8, 10))
        self.assertEqual(records[0].commission_value, 14.17)

    def test_link_de_produto_vira_mlb_e_link_de_catalogo_nao(self):
        produto, catalogo = parse_sales_payload([
            sale_payload(),
            sale_payload(
                id='2000017859207055',
                link='https://www.mercadolivre.com.br/tenis-fila/p/MLB19980968',
            ),
        ])

        self.assertEqual(produto.external_ref, 'MLB4452319413')
        # Catálogo é outro espaço de identificadores: casar por ele produziria
        # join errado, então fica vazio de propósito.
        self.assertEqual(catalogo.external_ref, '')

    def test_venda_sem_id_ou_data_utilizavel_e_descartada(self):
        records = parse_sales_payload([
            sale_payload(id=''),
            sale_payload(id='x1', date='sem data'),
            sale_payload(id='x2'),
        ])

        self.assertEqual([r.sale_id for r in records], ['x2'])

    def test_venda_repetida_no_payload_entra_uma_vez_so(self):
        records = parse_sales_payload([sale_payload(), sale_payload()])

        self.assertEqual(len(records), 1)


class IngestMLSalesTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )
        self.now = timezone.now()

    def _offer(self, *, external_id: str, title: str, suffix: str) -> Offer:
        return Offer.objects.create(
            marketplace=self.marketplace,
            title=title,
            normalized_title=title.lower(),
            external_id=external_id,
            offer_hash=f'hash-ml-sales-{suffix}',
            slug=f'offer-ml-sales-{suffix}',
            current_price=Decimal('144.00'),
            product_url='https://produto.mercadolivre.com.br/MLB-4452319413',
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    # -- idempotência --------------------------------------------------------

    def test_reimportar_a_mesma_janela_nao_duplica_venda(self):
        records = parse_sales_payload([sale_payload()])

        primeiro = ingest_ml_sales(records)
        segundo = ingest_ml_sales(parse_sales_payload([sale_payload()]))

        self.assertEqual(primeiro.created, 1)
        self.assertEqual(segundo.created, 0)
        self.assertEqual(segundo.updated, 1)
        self.assertEqual(MLAffiliateSale.objects.count(), 1)

    def test_mudanca_de_status_e_comissao_e_atualizada_e_contada(self):
        ingest_ml_sales(parse_sales_payload([sale_payload()]))

        result = ingest_ml_sales(parse_sales_payload([
            sale_payload(status='APPROVED', commissionValue=15.00),
        ]))

        venda = MLAffiliateSale.objects.get(sale_id='2000017859207054')
        self.assertEqual(result.status_changed, 1)
        self.assertEqual(venda.status, 'APPROVED')
        self.assertEqual(venda.commission_brl, Decimal('15.00'))

    def test_dry_run_nao_persiste(self):
        ingest_ml_sales(parse_sales_payload([sale_payload()]), commit=False)

        self.assertEqual(MLAffiliateSale.objects.count(), 0)

    # -- compra própria ------------------------------------------------------

    def test_status_rejected_marca_compra_propria_automaticamente(self):
        result = ingest_ml_sales(parse_sales_payload([
            sale_payload(status='REJECTED'),
        ]))

        venda = MLAffiliateSale.objects.get()
        self.assertTrue(venda.is_own_purchase)
        self.assertEqual(venda.own_purchase_source, OwnPurchaseSource.AUTO_REJECTED)
        self.assertEqual(result.auto_marked_own, 1)

    def test_marcacao_manual_sobrevive_a_reimportacao(self):
        """O caso que motivou o campo: 5 suplementos de maio seguiam `IN_REVIEW`
        em agosto. Marcados à mão, não podem voltar a contar como receita só
        porque o painel ainda não resolveu o status."""
        ingest_ml_sales(parse_sales_payload([sale_payload()]))
        venda = MLAffiliateSale.objects.get()
        venda.is_own_purchase = True
        venda.own_purchase_source = OwnPurchaseSource.MANUAL
        venda.save(update_fields=['is_own_purchase', 'own_purchase_source'])

        ingest_ml_sales(parse_sales_payload([sale_payload(status='APPROVED')]))

        venda.refresh_from_db()
        self.assertTrue(venda.is_own_purchase)
        self.assertEqual(venda.own_purchase_source, OwnPurchaseSource.MANUAL)
        self.assertEqual(venda.status, 'APPROVED')

    def test_venda_nova_de_loja_com_compra_propria_gera_aviso(self):
        ingest_ml_sales(parse_sales_payload([sale_payload(status='REJECTED')]))

        result = ingest_ml_sales(parse_sales_payload([
            sale_payload(id='2000017859207099', date='11/08/2026'),
        ]))

        self.assertTrue(
            any('BEGTRAVESSEIROS' in w for w in result.warnings),
            f'esperava aviso citando a loja; veio {result.warnings}',
        )

    # -- resolução de oferta -------------------------------------------------

    def test_resolve_oferta_por_mlb_do_link(self):
        offer = self._offer(
            external_id='MLB4452319413',
            title='Travesseiro Kit Nasa X 2 Un Duoflex',
            suffix='mlb',
        )

        ingest_ml_sales(parse_sales_payload([sale_payload()]))

        self.assertEqual(MLAffiliateSale.objects.get().offer_id, offer.id)

    def test_resolve_oferta_por_titulo_quando_link_e_de_catalogo(self):
        offer = self._offer(
            external_id='slug-tenis-fila-fastpace',
            title='Tênis Fila Fastpace Masculino Preto Corrida',
            suffix='titulo',
        )

        ingest_ml_sales(parse_sales_payload([
            sale_payload(
                id='3000',
                link='https://www.mercadolivre.com.br/tenis-fila/p/MLB19980968',
                productName='Tênis Fila Fastpace Masculino Preto Corrida',
            ),
        ]))

        self.assertEqual(MLAffiliateSale.objects.get().offer_id, offer.id)

    def test_titulo_diferente_nao_casa_com_oferta_alguma(self):
        self._offer(
            external_id='MLB999',
            title='Cafeteira Elétrica Mondial 30 Xícaras Inox',
            suffix='outro',
        )

        result = ingest_ml_sales(parse_sales_payload([sale_payload()]))

        venda = MLAffiliateSale.objects.get()
        self.assertIsNone(venda.offer_id)
        self.assertEqual(result.resolved_offers, 0)
        self.assertTrue(any('sem oferta correspondente' in w for w in result.warnings))

    def test_oferta_publicada_depois_da_janela_nao_e_considerada(self):
        """A venda acontece depois da publicação, nunca antes — oferta vista há
        mais de OFFER_LOOKBACK_DAYS fica fora do índice de candidatas."""
        antiga = self._offer(
            external_id='MLB4452319413',
            title='Travesseiro Kit Nasa X 2 Un Duoflex',
            suffix='antiga',
        )
        Offer.objects.filter(pk=antiga.pk).update(
            first_seen_at=self.now - timedelta(days=400),
        )

        ingest_ml_sales(parse_sales_payload([sale_payload()]))

        self.assertIsNone(MLAffiliateSale.objects.get().offer_id)

    def test_lote_registra_periodo_e_contagem(self):
        result = ingest_ml_sales(parse_sales_payload([
            sale_payload(id='a1', date='01/07/2026'),
            sale_payload(id='a2', date='15/08/2026'),
        ]))

        self.assertEqual(result.period_start, date(2026, 7, 1))
        self.assertEqual(result.period_end, date(2026, 8, 15))
        self.assertEqual(result.batch.rows_imported, 2)

    def test_lista_vazia_falha_alto_em_vez_de_criar_lote_vazio(self):
        with self.assertRaises(ValueError):
            ingest_ml_sales([])
