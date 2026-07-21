"""Testes de `MetricaCanalDiaria` (Sprint 7 - Tarefa 7.3, achado H9).

Cobre a constraint única (canal, data) — só 1 registro por canal por dia,
para não duplicar entrada manual do mesmo dia.
"""

from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.analytics.models import MetricaCanalDiaria
from apps.distribution.models import SocialChannel


class MetricaCanalDiariaModelTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )

    def test_creates_metric_with_required_fields(self):
        metrica = MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 20),
            membros=1500,
        )
        self.assertIsNone(metrica.posts_publicados)
        self.assertIsNone(metrica.cliques_estimados)
        self.assertIn('1500 membros', str(metrica))

    def test_unique_constraint_blocks_duplicate_canal_data(self):
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 20),
            membros=1500,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MetricaCanalDiaria.objects.create(
                    canal=self.channel,
                    data=date(2026, 7, 20),
                    membros=1600,
                )

    def test_same_channel_different_day_is_allowed(self):
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 20),
            membros=1500,
        )
        # Não deve levantar — dia diferente.
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 21),
            membros=1510,
        )
        self.assertEqual(MetricaCanalDiaria.objects.count(), 2)

    def test_different_channel_same_day_is_allowed(self):
        other_channel = SocialChannel.objects.create(
            name='Telegram Principal',
            code='telegram_main',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='@descontosbot',
        )
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 20),
            membros=1500,
        )
        # Não deve levantar — canal diferente, mesmo dia.
        MetricaCanalDiaria.objects.create(
            canal=other_channel,
            data=date(2026, 7, 20),
            membros=800,
        )
        self.assertEqual(MetricaCanalDiaria.objects.count(), 2)

    def test_canal_cannot_be_deleted_while_referenced(self):
        MetricaCanalDiaria.objects.create(
            canal=self.channel,
            data=date(2026, 7, 20),
            membros=1500,
        )
        # on_delete=PROTECT: histórico de métricas não pode sumir com o canal.
        from django.db.models.deletion import ProtectedError

        with self.assertRaises(ProtectedError):
            self.channel.delete()
