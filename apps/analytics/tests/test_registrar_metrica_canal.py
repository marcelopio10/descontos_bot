"""Testes do comando `registrar_metrica_canal` (Sprint 7 - Tarefa 7.3).

Entrada manual periódica de contagem agregada de membros/seguidores por
canal — LGPD: só agregado, nunca dado individual.
"""

from datetime import date
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.analytics.models import FonteMetricaCanal, MetricaCanalDiaria
from apps.distribution.models import SocialChannel


class RegistrarMetricaCanalCommandTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )

    def test_creates_metric(self):
        out = StringIO()
        call_command(
            'registrar_metrica_canal',
            '--canal', 'whatsapp_principal',
            '--data', '2026-07-20',
            '--membros', '1500',
            '--fonte', 'informado_dono',
            stdout=out,
        )

        metrica = MetricaCanalDiaria.objects.get(canal=self.channel, data=date(2026, 7, 20))
        self.assertEqual(metrica.membros, 1500)
        self.assertEqual(metrica.fonte, FonteMetricaCanal.INFORMADO_DONO)
        self.assertIn('criada', out.getvalue())

    def test_rerunning_same_day_updates_instead_of_duplicating(self):
        call_command(
            'registrar_metrica_canal',
            '--canal', 'whatsapp_principal',
            '--data', '2026-07-20',
            '--membros', '1500',
            '--fonte', 'informado_dono',
        )
        out = StringIO()
        call_command(
            'registrar_metrica_canal',
            '--canal', 'whatsapp_principal',
            '--data', '2026-07-20',
            '--membros', '1600',
            '--fonte', 'informado_dono',
            stdout=out,
        )

        self.assertEqual(MetricaCanalDiaria.objects.count(), 1)
        metrica = MetricaCanalDiaria.objects.get(canal=self.channel, data=date(2026, 7, 20))
        self.assertEqual(metrica.membros, 1600)
        self.assertIn('atualizada', out.getvalue())

    def test_optional_fields(self):
        call_command(
            'registrar_metrica_canal',
            '--canal', 'whatsapp_principal',
            '--data', '2026-07-20',
            '--membros', '1500',
            '--posts-publicados', '3',
            '--cliques-estimados', '42',
            '--fonte', 'informado_dono',
        )
        metrica = MetricaCanalDiaria.objects.get(canal=self.channel, data=date(2026, 7, 20))
        self.assertEqual(metrica.posts_publicados, 3)
        self.assertEqual(metrica.cliques_estimados, 42)

    def test_unknown_channel_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                'registrar_metrica_canal',
                '--canal', 'canal_inexistente',
                '--data', '2026-07-20',
                '--membros', '1500',
            )

    def test_invalid_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                'registrar_metrica_canal',
                '--canal', 'whatsapp_principal',
                '--data', '20-07-2026',
                '--membros', '1500',
            )
