from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.panel.models import Setting
from apps.scraping.services import ml_cookie_monitor as monitor


class DiasRestantesEstimadosTests(TestCase):
    def test_returns_none_when_setting_never_configured(self):
        """Sem `ml_cookie_atualizado_em` setada, a estimativa não pode ser
        calculada — comportamento seguro por ausência de dado, não um erro."""
        self.assertIsNone(monitor.dias_restantes_estimados())

    def test_returns_none_for_malformed_timestamp(self):
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value='nao-e-uma-data-iso')
        self.assertIsNone(monitor.dias_restantes_estimados())

    def test_returns_none_for_blank_value(self):
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value='')
        self.assertIsNone(monitor.dias_restantes_estimados())

    def test_uses_default_validade_dias_when_setting_absent(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=10)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        # SETTING_VALIDADE_DIAS não configurada -> usa DEFAULT_VALIDADE_DIAS

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now):
            dias = monitor.dias_restantes_estimados()

        self.assertEqual(dias, monitor.DEFAULT_VALIDADE_DIAS - 10)

    def test_respects_custom_validade_dias_setting(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=5)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='15')

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now):
            dias = monitor.dias_restantes_estimados()

        self.assertEqual(dias, 10)


class VerificarCookiePrestesAVencerTests(TestCase):
    def test_no_setting_configured_never_fires_false_positive(self):
        """Requisito de segurança: sem `ml_cookie_atualizado_em`, o alerta
        preditivo NUNCA dispara (só o reativo continua funcionando)."""
        with patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            disparou = monitor.verificar_cookie_prestes_a_vencer()

        self.assertFalse(disparou)
        mock_alert.assert_not_called()

    def test_recent_update_within_safety_margin_does_not_alert(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=1)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            disparou = monitor.verificar_cookie_prestes_a_vencer()

        self.assertFalse(disparou)
        mock_alert.assert_not_called()

    def test_close_to_expiring_triggers_alert(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=28)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')  # faltam 2 dias

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            disparou = monitor.verificar_cookie_prestes_a_vencer()

        self.assertTrue(disparou)
        mock_alert.assert_called_once()
        self.assertEqual(mock_alert.call_args.kwargs.get('categoria'), 'ml_cookie_prestes_a_vencer')
        mensagem = mock_alert.call_args.args[0]
        self.assertIn('2 dia', mensagem)

    def test_already_past_expiration_estimate_triggers_alert(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=45)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')  # já venceu há ~15 dias

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            disparou = monitor.verificar_cookie_prestes_a_vencer()

        self.assertTrue(disparou)
        mensagem = mock_alert.call_args.args[0]
        self.assertIn('já venceu', mensagem)

    def test_custom_dias_antecedencia_parameter_is_respected(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=20)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')  # faltam 10 dias

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            # margem padrão (3 dias) não dispara com 10 dias restantes
            self.assertFalse(monitor.verificar_cookie_prestes_a_vencer())
            mock_alert.assert_not_called()
            # margem alargada para 15 dias já dispara
            self.assertTrue(monitor.verificar_cookie_prestes_a_vencer(dias_antecedencia=15))
            mock_alert.assert_called_once()


class CheckMlCookieHealthCommandTests(TestCase):
    def test_dry_run_without_setting_never_alerts(self):
        with patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            call_command('check_ml_cookie_health', '--dry-run')

        mock_alert.assert_not_called()

    def test_dry_run_close_to_expiring_reports_without_alerting(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=29)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            call_command('check_ml_cookie_health', '--dry-run')

        mock_alert.assert_not_called()

    def test_real_run_close_to_expiring_alerts(self):
        fixed_now = timezone.now()
        atualizado_em = fixed_now - timedelta(days=29)
        Setting.objects.create(key=monitor.SETTING_ATUALIZADO_EM, value=atualizado_em.isoformat())
        Setting.objects.create(key=monitor.SETTING_VALIDADE_DIAS, value='30')

        with patch('apps.scraping.services.ml_cookie_monitor.timezone.now', return_value=fixed_now), \
                patch('apps.scraping.services.ml_cookie_monitor.enviar_alerta_operador') as mock_alert:
            call_command('check_ml_cookie_health')

        mock_alert.assert_called_once()
