"""Cobertura da procedência da métrica de canal (item 8 da Onda 1, 2026-08-23).

O defeito que estes testes impedem de voltar: estimativa gravada como se fosse
medição. Os três registros que existiam diziam 1.240 membros no WhatsApp (real
~100) e 860 no Telegram (real 6) — erro de 12x e 143x no número que orienta todo
o growth. Dado errado é pior que dado ausente, porque induz decisão.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.analytics.models import FonteMetricaCanal, MetricaCanalDiaria
from apps.analytics.services.operational_metrics import channel_membership_series
from apps.distribution.models import SocialChannel


class MetricaCanalTestCase(TestCase):
    def setUp(self):
        self.canal, _ = SocialChannel.objects.get_or_create(
            code='whatsapp_principal',
            defaults={
                'name': 'WhatsApp principal',
                'channel_type': 'whatsapp',
                'target': 'grupo',
            },
        )

    def _metrica(self, membros: int, fonte: str, days_ago: int = 1):
        return MetricaCanalDiaria.objects.create(
            canal=self.canal,
            data=timezone.localdate() - timedelta(days=days_ago),
            membros=membros,
            fonte=fonte,
        )


class FonteDefaultTests(MetricaCanalTestCase):
    def test_sem_fonte_declarada_o_registro_nasce_estimado(self):
        """Quem não declara procedência não ganha o benefício da dúvida."""
        metrica = MetricaCanalDiaria.objects.create(
            canal=self.canal,
            data=timezone.localdate(),
            membros=1240,
        )
        self.assertEqual(metrica.fonte, FonteMetricaCanal.ESTIMADO)


class CurvaDoPainelTests(MetricaCanalTestCase):
    def test_ponto_estimado_fica_fora_da_curva_e_e_contado(self):
        self._metrica(1240, FonteMetricaCanal.ESTIMADO, days_ago=10)
        self._metrica(103, FonteMetricaCanal.INFORMADO_DONO, days_ago=2)

        report = channel_membership_series(days=30)

        pontos = [p for s in report.series for p in s.points]
        self.assertEqual([p.membros for p in pontos], [103])
        self.assertEqual(report.unverified_points, 1)

    def test_curva_vazia_quando_so_ha_estimativa(self):
        """Curva vazia é o resultado correto aqui — melhor que curva errada."""
        self._metrica(1240, FonteMetricaCanal.ESTIMADO, days_ago=3)

        report = channel_membership_series(days=30)

        self.assertEqual(report.series, [])
        self.assertEqual(report.unverified_points, 1)


@patch('apps.analytics.management.commands.lembrar_metrica_canal.enviar_alerta_operador')
class LembreteTests(MetricaCanalTestCase):
    """O alerta é sempre mockado: nenhum teste pode mandar mensagem de verdade
    para o operador, mesmo com credenciais reais no `.env`."""

    def test_cobra_quando_a_ultima_medicao_verificada_envelhece(self, mock_alerta):
        self._metrica(103, FonteMetricaCanal.INFORMADO_DONO, days_ago=30)

        call_command('lembrar_metrica_canal', '--canal', 'whatsapp_principal')

        mock_alerta.assert_called_once()
        mensagem = mock_alerta.call_args[0][0]
        self.assertIn('30 dias', mensagem)

    def test_nao_cobra_quando_a_medicao_esta_fresca(self, mock_alerta):
        self._metrica(103, FonteMetricaCanal.INFORMADO_DONO, days_ago=2)

        call_command('lembrar_metrica_canal', '--canal', 'whatsapp_principal')

        mock_alerta.assert_not_called()

    def test_estimativa_recente_nao_cala_o_lembrete(self, mock_alerta):
        """Estimativa não conta como medição — senão o palpite silencia a cobrança."""
        self._metrica(1240, FonteMetricaCanal.ESTIMADO, days_ago=1)

        call_command('lembrar_metrica_canal', '--canal', 'whatsapp_principal')

        mock_alerta.assert_called_once()
        self.assertIn('Nenhuma medição verificada', mock_alerta.call_args[0][0])

    def test_dry_run_nao_dispara_alerta(self, mock_alerta):
        self._metrica(103, FonteMetricaCanal.INFORMADO_DONO, days_ago=30)

        call_command('lembrar_metrica_canal', '--canal', 'whatsapp_principal', '--dry-run')

        mock_alerta.assert_not_called()
