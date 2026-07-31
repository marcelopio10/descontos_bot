"""Teste da seção de membros/seguidores no `painel_operacional` (Sprint 7 -
Tarefa 7.3, achado H9): confirma que a curva por canal aparece tanto na
impressão no terminal quanto no JSON gravado em site/painel-operacional.json.
"""

import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.models import MetricaCanalDiaria
from apps.distribution.models import SocialChannel


class PainelOperacionalMembershipTests(TestCase):
    def setUp(self):
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )
        self.today = timezone.now().date()
        MetricaCanalDiaria.objects.create(
            canal=self.channel, data=self.today, membros=1500,
        )

    def test_membership_section_printed_and_written_to_json(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            with override_settings(SITE_PUBLIC_DIR=tmp_dir):
                out = StringIO()
                call_command('painel_operacional', stdout=out)

                printed = out.getvalue()
                self.assertIn('Membros/seguidores por canal', printed)
                self.assertIn('WhatsApp Principal', printed)
                self.assertIn('1500', printed)

                with open(f'{tmp_dir}/painel-operacional.json', encoding='utf-8') as fh:
                    payload = json.load(fh)

        self.assertIn('membership', payload)
        series = payload['membership']['series']
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]['channel_code'], 'whatsapp_principal')
        self.assertEqual(series[0]['points'][0]['membros'], 1500)
        self.assertEqual(series[0]['points'][0]['data'], self.today.isoformat())
