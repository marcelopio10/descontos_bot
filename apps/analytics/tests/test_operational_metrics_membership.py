"""Testes de `channel_membership_series` (Sprint 7 - Tarefa 7.3, achado H9).

Série temporal de membros/seguidores por canal, a partir de
`MetricaCanalDiaria` (entrada manual periódica). Cobre: agregação por canal
ordenada por data, fallback de `posts_publicados` para a contagem real de
`Delivery` quando não preenchido manualmente, respeito ao valor manual quando
informado, e o corte pela janela `days`.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import MetricaCanalDiaria
from apps.analytics.services.operational_metrics import (
    DEFAULT_MEMBERSHIP_DAYS,
    channel_membership_series,
)
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class ChannelMembershipSeriesTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.today = self.now.date()

        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )
        self.marketplace = Marketplace.objects.create(
            name='Amazon', code='amazon', base_url='https://amazon.example.com',
        )

    def _offer(self, hash_suffix):
        return Offer.objects.create(
            marketplace=self.marketplace,
            title=f'Produto {hash_suffix}',
            normalized_title=f'produto {hash_suffix}',
            offer_hash=f'hash-membership-{hash_suffix}',
            slug=f'produto-membership-{hash_suffix}',
            current_price=Decimal('50.00'),
            product_url=f'https://example.com/p/{hash_suffix}',
            first_seen_at=self.now,
            last_seen_at=self.now,
        )

    def _delivery(self, hash_suffix, sent_at):
        return Delivery.objects.create(
            offer=self._offer(hash_suffix),
            social_channel=self.channel,
            message='mensagem',
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at=sent_at,
        )

    def test_default_days_matches_constant(self):
        report = channel_membership_series()
        self.assertEqual(report.days, DEFAULT_MEMBERSHIP_DAYS)

    def test_series_groups_by_channel_ordered_by_date(self):
        MetricaCanalDiaria.objects.create(
            canal=self.channel, data=self.today, membros=1500,
        )
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=self.today - timezone.timedelta(days=7),
            membros=1400,
        )

        report = channel_membership_series(days=30)

        self.assertEqual(len(report.series), 1)
        serie = report.series[0]
        self.assertEqual(serie.channel_code, 'whatsapp_principal')
        # Ordenado por data crescente (query usa order_by('canal__code', 'data')).
        self.assertEqual([p.membros for p in serie.points], [1400, 1500])

    def test_posts_publicados_falls_back_to_delivery_count(self):
        self._delivery('d1', self.now)
        self._delivery('d2', self.now)

        MetricaCanalDiaria.objects.create(
            canal=self.channel, data=self.today, membros=1500,
        )  # posts_publicados não informado

        report = channel_membership_series(days=30)
        point = report.series[0].points[0]
        self.assertEqual(point.posts_publicados, 2)

    def test_posts_publicados_respects_manual_value(self):
        self._delivery('d1', self.now)

        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=self.today,
            membros=1500,
            posts_publicados=9,  # valor manual não deve ser sobrescrito
        )

        report = channel_membership_series(days=30)
        point = report.series[0].points[0]
        self.assertEqual(point.posts_publicados, 9)

    def test_days_window_excludes_old_entries(self):
        old_date = self.today - timezone.timedelta(days=120)
        MetricaCanalDiaria.objects.create(
            canal=self.channel, data=old_date, membros=1000,
        )

        report = channel_membership_series(days=30)
        self.assertEqual(report.series, [])

    def test_no_metrics_returns_empty_series(self):
        report = channel_membership_series(days=30)
        self.assertEqual(report.series, [])
