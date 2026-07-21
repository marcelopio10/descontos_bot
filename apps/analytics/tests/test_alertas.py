from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.analytics.services import alertas
from apps.distribution.services.telegram_client import TelegramClientError, TelegramSendResult


class EnviarAlertaOperadorTests(SimpleTestCase):
    """Verifica a lógica de `alertas.py` SEM jamais chamar a API real do Telegram.

    `TelegramClient` é sempre mockado — mesmo com credenciais reais no `.env`,
    nenhum destes testes pode disparar uma mensagem de verdade para o operador.
    """

    @override_settings(
        OPERATOR_ALERT_BOT_TOKEN='',
        OPERATOR_ALERT_CHAT_ID='',
        INSTAGRAM_HANDOFF_BOT_TOKEN='fake-token',
        INSTAGRAM_HANDOFF_CHAT_ID='fake-chat-id',
    )
    @patch('apps.analytics.services.alertas.TelegramClient')
    def test_sends_via_handoff_bot_when_operator_specific_vars_are_absent(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.send_message.return_value = TelegramSendResult(
            success=True, message_id='1', sent_at=None, error_message='',
        )
        mock_client_cls.return_value = mock_client

        alertas.enviar_alerta_operador('teste de mensagem', categoria='minha_categoria')

        mock_client_cls.assert_called_once_with(token='fake-token')
        mock_client.send_message.assert_called_once()
        _, kwargs = mock_client.send_message.call_args
        self.assertEqual(kwargs['chat_id'], 'fake-chat-id')
        self.assertIn('teste de mensagem', kwargs['text_html'])
        self.assertIn('minha_categoria', kwargs['text_html'])

    @override_settings(
        OPERATOR_ALERT_BOT_TOKEN='operator-token',
        OPERATOR_ALERT_CHAT_ID='operator-chat',
        INSTAGRAM_HANDOFF_BOT_TOKEN='fallback-token',
        INSTAGRAM_HANDOFF_CHAT_ID='fallback-chat',
    )
    @patch('apps.analytics.services.alertas.TelegramClient')
    def test_prefers_operator_specific_vars_over_handoff_fallback(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.send_message.return_value = TelegramSendResult(
            success=True, message_id='1', sent_at=None, error_message='',
        )
        mock_client_cls.return_value = mock_client

        alertas.enviar_alerta_operador('teste')

        mock_client_cls.assert_called_once_with(token='operator-token')
        _, kwargs = mock_client.send_message.call_args
        self.assertEqual(kwargs['chat_id'], 'operator-chat')

    @override_settings(OPERATOR_ALERT_BOT_TOKEN='', OPERATOR_ALERT_CHAT_ID='',
                        INSTAGRAM_HANDOFF_BOT_TOKEN='', INSTAGRAM_HANDOFF_CHAT_ID='')
    @patch('apps.analytics.services.alertas.TelegramClient')
    def test_does_nothing_and_does_not_raise_when_no_credentials_configured(self, mock_client_cls):
        with self.assertLogs('apps.analytics.services.alertas', level='WARNING') as cm:
            alertas.enviar_alerta_operador('não deveria enviar')

        mock_client_cls.assert_not_called()
        self.assertTrue(any('nao_configurado' in message for message in cm.output))

    @override_settings(
        OPERATOR_ALERT_BOT_TOKEN='fake-token',
        OPERATOR_ALERT_CHAT_ID='fake-chat-id',
    )
    @patch('apps.analytics.services.alertas.TelegramClient')
    def test_swallows_telegram_client_error_without_raising(self, mock_client_cls):
        mock_client_cls.side_effect = TelegramClientError('boom')

        with self.assertLogs('apps.analytics.services.alertas', level='WARNING'):
            # Não deve lançar exceção mesmo com falha no client.
            alertas.enviar_alerta_operador('teste')

    @override_settings(
        OPERATOR_ALERT_BOT_TOKEN='fake-token',
        OPERATOR_ALERT_CHAT_ID='fake-chat-id',
    )
    @patch('apps.analytics.services.alertas.TelegramClient')
    def test_logs_warning_when_send_result_is_not_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.send_message.return_value = TelegramSendResult(
            success=False, message_id='', sent_at=None, error_message='falhou',
        )
        mock_client_cls.return_value = mock_client

        with self.assertLogs('apps.analytics.services.alertas', level='WARNING') as cm:
            alertas.enviar_alerta_operador('teste')

        self.assertTrue(any('envio_falhou' in message for message in cm.output))


class AlertaHelpersFormatMessageTests(SimpleTestCase):
    """Testa que os helpers específicos formatam a mensagem e delegam para `enviar_alerta_operador`."""

    @patch('apps.analytics.services.alertas.enviar_alerta_operador')
    def test_alertar_scraper_zero_ofertas_formats_message(self, mock_enviar):
        alertas.alertar_scraper_zero_ofertas('amazon', 42, 'detalhe extra')

        mock_enviar.assert_called_once()
        (mensagem,), kwargs = mock_enviar.call_args
        self.assertIn('amazon', mensagem)
        self.assertIn('42', mensagem)
        self.assertEqual(kwargs['categoria'], 'scraper_zero_ofertas')

    @patch('apps.analytics.services.alertas.enviar_alerta_operador')
    def test_alertar_curadoria_falhas_consecutivas_formats_message(self, mock_enviar):
        alertas.alertar_curadoria_falhas_consecutivas('whatsapp_main', 7, 2)

        mock_enviar.assert_called_once()
        (mensagem,), kwargs = mock_enviar.call_args
        self.assertIn('whatsapp_main', mensagem)
        self.assertIn('2', mensagem)
        self.assertEqual(kwargs['categoria'], 'curadoria_falhas_consecutivas')

    @patch('apps.analytics.services.alertas.enviar_alerta_operador')
    def test_alertar_canal_sem_entrega_formats_message(self, mock_enviar):
        alertas.alertar_canal_sem_entrega('telegram_main', 24)

        mock_enviar.assert_called_once()
        (mensagem,), kwargs = mock_enviar.call_args
        self.assertIn('telegram_main', mensagem)
        self.assertEqual(kwargs['categoria'], 'canal_sem_entrega')

    @patch('apps.analytics.services.alertas.enviar_alerta_operador')
    def test_alertar_observer_atrasado_formats_message(self, mock_enviar):
        alertas.alertar_observer_atrasado(30)

        mock_enviar.assert_called_once()
        (mensagem,), kwargs = mock_enviar.call_args
        self.assertIn('30', mensagem)
        self.assertEqual(kwargs['categoria'], 'observer_atrasado')
