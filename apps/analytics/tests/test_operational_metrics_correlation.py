"""Testes de `deliveries_vs_commission_by_marketplace_week` (Sprint 4 - Tarefa 4.2).

Cruza, por marketplace e por semana, envios (`Delivery`) com comissão
(`AffiliateConversion`). Cobre: agregação correta por marketplace/semana,
rótulo "correlação (ML/Amazon)" vs "atribuição (Shopee, via subId)", linhas
que existem só de um lado (só envio ou só comissão na semana) e o corte pela
janela `weeks`.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import AffiliateConversion, AffiliateImportBatch, AffiliateSource
from apps.analytics.services.operational_metrics import (
    ATTRIBUTION_LABEL,
    CORRELATION_LABEL,
    DEFAULT_WEEKS,
    deliveries_vs_commission_by_marketplace_week,
)
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class DeliveriesVsCommissionByMarketplaceWeekTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.mkt_amazon = Marketplace.objects.create(
            name='Amazon', code='amazon', base_url='https://amazon.example.com',
        )
        self.mkt_ml = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre', base_url='https://ml.example.com',
        )
        self.mkt_shopee = Marketplace.objects.create(
            name='Shopee', code='shopee', base_url='https://shopee.example.com',
        )

        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )

    def _offer(self, marketplace, hash_suffix):
        return Offer.objects.create(
            marketplace=marketplace,
            title=f'Produto {hash_suffix}',
            normalized_title=f'produto {hash_suffix}',
            offer_hash=f'hash-correlation-{hash_suffix}',
            slug=f'produto-correlation-{hash_suffix}',
            current_price=Decimal('50.00'),
            product_url=f'https://example.com/p/{hash_suffix}',
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    def _delivery(self, marketplace, hash_suffix, sent_at):
        return Delivery.objects.create(
            offer=self._offer(marketplace, hash_suffix),
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=sent_at,
        )

    def _conversion(self, source, external_ref, period_start, commission, conversions=1):
        batch = AffiliateImportBatch.objects.create(
            source=source,
            payload_sha256=f'sha-{external_ref}',
        )
        return AffiliateConversion.objects.create(
            source=source,
            external_ref=external_ref,
            period_start=period_start,
            period_end=period_start,
            commission_brl=Decimal(commission),
            conversions=conversions,
            batch=batch,
        )

    def test_default_weeks_matches_constant(self):
        report = deliveries_vs_commission_by_marketplace_week()
        self.assertEqual(report.weeks, DEFAULT_WEEKS)

    def test_aggregates_sent_count_and_commission_per_marketplace_current_week(self):
        # Amazon: 2 envios na semana atual.
        self._delivery(self.mkt_amazon, 'amz-1', self.now)
        self._delivery(self.mkt_amazon, 'amz-2', self.now)
        # Mercado Livre: 1 envio.
        self._delivery(self.mkt_ml, 'ml-1', self.now)
        # Shopee: 1 envio.
        self._delivery(self.mkt_shopee, 'shopee-1', self.now)

        self._conversion(AffiliateSource.AMAZON, 'ASIN1', self.now.date(), '15.00', conversions=3)
        self._conversion(AffiliateSource.MERCADO_LIVRE, 'MLB1', self.now.date(), '8.00', conversions=2)
        self._conversion(AffiliateSource.SHOPEE, 'SHP1', self.now.date(), '4.50', conversions=1)

        # Dado antigo (40 dias) fora da janela de 2 semanas — não deve aparecer.
        old_dt = self.now - timezone.timedelta(days=40)
        self._delivery(self.mkt_amazon, 'amz-old', old_dt)
        self._conversion(AffiliateSource.AMAZON, 'ASIN_OLD', old_dt.date(), '99.00', conversions=9)

        report = deliveries_vs_commission_by_marketplace_week(weeks=2)

        by_marketplace = {row.marketplace_code: row for row in report.rows}
        self.assertEqual(set(by_marketplace), {'amazon', 'mercadolivre', 'shopee'})

        amazon_row = by_marketplace['amazon']
        self.assertEqual(amazon_row.sent_count, 2)
        self.assertEqual(amazon_row.commission_brl, Decimal('15.00'))
        self.assertEqual(amazon_row.conversions, 3)
        self.assertEqual(amazon_row.label, CORRELATION_LABEL)

        ml_row = by_marketplace['mercadolivre']
        self.assertEqual(ml_row.sent_count, 1)
        self.assertEqual(ml_row.commission_brl, Decimal('8.00'))
        self.assertEqual(ml_row.label, CORRELATION_LABEL)

        shopee_row = by_marketplace['shopee']
        self.assertEqual(shopee_row.sent_count, 1)
        self.assertEqual(shopee_row.commission_brl, Decimal('4.50'))
        self.assertEqual(shopee_row.label, ATTRIBUTION_LABEL)

    def test_row_appears_with_zero_commission_when_only_deliveries_exist_in_week(self):
        self._delivery(self.mkt_amazon, 'amz-only-delivery', self.now)

        report = deliveries_vs_commission_by_marketplace_week(weeks=2)

        amazon_rows = [r for r in report.rows if r.marketplace_code == 'amazon']
        self.assertEqual(len(amazon_rows), 1)
        self.assertEqual(amazon_rows[0].sent_count, 1)
        self.assertEqual(amazon_rows[0].commission_brl, Decimal('0'))
        self.assertEqual(amazon_rows[0].conversions, 0)

    def test_row_appears_with_zero_sent_count_when_only_commission_exists_in_week(self):
        self._conversion(AffiliateSource.SHOPEE, 'SHP-only-commission', self.now.date(), '7.25')

        report = deliveries_vs_commission_by_marketplace_week(weeks=2)

        shopee_rows = [r for r in report.rows if r.marketplace_code == 'shopee']
        self.assertEqual(len(shopee_rows), 1)
        self.assertEqual(shopee_rows[0].sent_count, 0)
        self.assertEqual(shopee_rows[0].commission_brl, Decimal('7.25'))
        self.assertEqual(shopee_rows[0].label, ATTRIBUTION_LABEL)

    def test_weeks_window_excludes_data_older_than_cutoff(self):
        old_dt = self.now - timezone.timedelta(days=70)  # 10 semanas atrás
        self._delivery(self.mkt_amazon, 'amz-very-old', old_dt)
        self._conversion(AffiliateSource.AMAZON, 'ASIN_VERY_OLD', old_dt.date(), '42.00')

        report_narrow = deliveries_vs_commission_by_marketplace_week(weeks=8)
        self.assertEqual(report_narrow.rows, [])

        report_wide = deliveries_vs_commission_by_marketplace_week(weeks=11)
        self.assertEqual(len(report_wide.rows), 1)
        self.assertEqual(report_wide.rows[0].marketplace_code, 'amazon')
        self.assertEqual(report_wide.rows[0].sent_count, 1)
        self.assertEqual(report_wide.rows[0].commission_brl, Decimal('42.00'))

    def test_note_mentions_restr03_correlation_caveat(self):
        report = deliveries_vs_commission_by_marketplace_week()
        self.assertIn('correlação', report.note.lower())
