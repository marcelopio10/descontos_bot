"""Achado A2 (diagnóstico 2026-08-18): queda de sessão do WhatsApp não alertava ninguém.

`SessaoIndisponivelError` interrompia o lote em 3 pontos (`run_bot` fluxo legado,
`run_bot` fluxo de curadoria IA, `consumir_fila_whatsapp`) e os pré-checks abortavam
o ciclo — todos apenas com `stdout.write` + `log.error`. Na prática o bot parava de
enviar e só se descobria olhando log.

Estes testes travam o comportamento novo: todo caminho que interrompe/aborta envio por
sessão indisponível chama `enviar_alerta_operador` com a categoria
`whatsapp_sessao_indisponivel`. Nenhum envio real acontece aqui — a entrega e o status
da sessão são mockados.

Ver `docs/DIAGNOSTICO_ENVIOS_COLETA_2026-08-18.md`.
"""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.curation.models import CurationRun
from apps.distribution.services.delivery import SessaoIndisponivelError
from apps.distribution.services.whatsapp_client import WhatsAppClientError
from apps.marketplaces.models import Marketplace
from apps.orchestration.management.commands.run_bot import Command as RunBotCommand
from apps.orchestration.tests.test_decoupled_queue import DecoupledQueueFlagTestsMixin
from apps.panel.models import Setting


ALERT_CATEGORY = 'whatsapp_sessao_indisponivel'

CONSUMIR = 'apps.orchestration.management.commands.consumir_fila_whatsapp'
RUN_BOT = 'apps.orchestration.management.commands.run_bot'


def _categorias(alert_mock) -> list[str]:
    return [call.kwargs.get('categoria', '') for call in alert_mock.call_args_list]


class ConsumirFilaSessionAlertTests(DecoupledQueueFlagTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.channel = self._make_channel(code='whatsapp_homolog_alerta', target='grupo-homolog-alerta')
        self.offer = self._make_offer(self.marketplace, 'alerta-1')

    def test_session_dropped_mid_batch_alerts_operator(self):
        batch = self._create_ready_batch(self.channel, self.offer, mode=CurationRun.Mode.HOMOLOG)
        out = StringIO()

        with (
            patch(
                f'{CONSUMIR}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=True, jid='55119999@s.whatsapp.net'),
            ),
            patch(
                f'{CONSUMIR}.deliver_curated_item_to_whatsapp',
                side_effect=SessaoIndisponivelError('sessão caiu no meio do envio'),
            ),
            patch(f'{CONSUMIR}.enviar_alerta_operador') as alerta,
        ):
            call_command('consumir_fila_whatsapp', '--channel', self.channel.code, stdout=out)

        alerta.assert_called_once()
        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        mensagem = alerta.call_args.args[0]
        self.assertIn(f'lote curado #{batch.id}', mensagem)
        self.assertIn(self.channel.code, mensagem)
        self.assertIn('sessão caiu no meio do envio', mensagem)

    def test_precheck_disconnected_alerts_operator_before_sending(self):
        self._create_ready_batch(self.channel, self.offer, mode=CurationRun.Mode.HOMOLOG)
        out = StringIO()

        with (
            patch(
                f'{CONSUMIR}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=False, jid=''),
            ),
            patch(f'{CONSUMIR}.deliver_curated_item_to_whatsapp') as deliver,
            patch(f'{CONSUMIR}.enviar_alerta_operador') as alerta,
        ):
            call_command('consumir_fila_whatsapp', '--channel', self.channel.code, stdout=out)

        deliver.assert_not_called()
        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        self.assertIn('não conectada', alerta.call_args.args[0])

    def test_precheck_client_error_alerts_operator(self):
        self._create_ready_batch(self.channel, self.offer, mode=CurationRun.Mode.HOMOLOG)
        out = StringIO()

        with (
            patch(
                f'{CONSUMIR}.get_whatsapp_session_status',
                side_effect=WhatsAppClientError('gateway fora do ar'),
            ),
            patch(f'{CONSUMIR}.deliver_curated_item_to_whatsapp') as deliver,
            patch(f'{CONSUMIR}.enviar_alerta_operador') as alerta,
        ):
            call_command('consumir_fila_whatsapp', '--channel', self.channel.code, stdout=out)

        deliver.assert_not_called()
        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        self.assertIn('gateway fora do ar', alerta.call_args.args[0])

    def test_dry_run_never_alerts(self):
        """Dry-run não envia nada, então não pode gerar alerta operacional."""
        self._create_ready_batch(self.channel, self.offer)
        out = StringIO()

        with patch(f'{CONSUMIR}.enviar_alerta_operador') as alerta:
            call_command('consumir_fila_whatsapp', '--dry-run', '--channel', self.channel.code, stdout=out)

        alerta.assert_not_called()


class RunBotSessionAlertTests(DecoupledQueueFlagTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.channel = self._make_channel(code='whatsapp_homolog_runbot', target='grupo-homolog-runbot')
        self.offer = self._make_offer(self.marketplace, 'runbot-1')

    def test_ai_curation_flow_alerts_when_session_drops_mid_batch(self):
        """Fluxo de curadoria IA embutido no run_bot (fila desacoplada explicitamente off)."""
        batch = self._create_ready_batch(self.channel, self.offer, mode=CurationRun.Mode.HOMOLOG)
        Setting.objects.create(key='usa_fila_desacoplada', value='false')
        out = StringIO()

        with (
            patch(f'{RUN_BOT}.call_command'),
            patch(
                f'{RUN_BOT}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=True, jid='55119999@s.whatsapp.net'),
            ),
            patch(
                f'{RUN_BOT}.deliver_curated_item_to_whatsapp',
                side_effect=SessaoIndisponivelError('sessão caiu no fluxo IA'),
            ),
            patch(f'{RUN_BOT}.enviar_alerta_operador') as alerta,
        ):
            call_command(
                'run_bot',
                '--once',
                '--skip-scraping',
                '--channel',
                self.channel.code,
                '--ai-curation',
                stdout=out,
            )

        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        mensagem = alerta.call_args.args[0]
        self.assertIn(f'lote curado #{batch.id}', mensagem)
        self.assertIn('sessão caiu no fluxo IA', mensagem)

    def test_legacy_flow_alerts_when_session_drops_mid_batch(self):
        """Fluxo legado (selector por lógica, sem curadoria IA)."""
        out = StringIO()

        with (
            patch(f'{RUN_BOT}.select_offers_for_channel', return_value=[self.offer]),
            patch(
                f'{RUN_BOT}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=True, jid='55119999@s.whatsapp.net'),
            ),
            patch(
                f'{RUN_BOT}.deliver_offer_to_channel',
                side_effect=SessaoIndisponivelError('sessão caiu no fluxo legado'),
            ),
            patch(f'{RUN_BOT}.enviar_alerta_operador') as alerta,
        ):
            call_command(
                'run_bot',
                '--once',
                '--skip-scraping',
                '--channel',
                self.channel.code,
                '--legacy-selector',
                stdout=out,
            )

        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        mensagem = alerta.call_args.args[0]
        self.assertIn('fluxo legado', mensagem)
        self.assertIn(f'oferta #{self.offer.id}', mensagem)

    def test_precheck_client_error_alerts_operator(self):
        command = RunBotCommand()
        command.stdout = StringIO()

        with (
            patch(
                f'{RUN_BOT}.get_whatsapp_session_status',
                side_effect=WhatsAppClientError('evolution indisponível'),
            ),
            patch(f'{RUN_BOT}.enviar_alerta_operador') as alerta,
        ):
            self.assertFalse(command._check_whatsapp_session())

        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        self.assertIn('evolution indisponível', alerta.call_args.args[0])

    def test_precheck_disconnected_alerts_operator(self):
        command = RunBotCommand()
        command.stdout = StringIO()

        with (
            patch(
                f'{RUN_BOT}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=False, jid=''),
            ),
            patch(f'{RUN_BOT}.enviar_alerta_operador') as alerta,
        ):
            self.assertFalse(command._check_whatsapp_session())

        self.assertEqual(_categorias(alerta), [ALERT_CATEGORY])
        self.assertIn('não conectada', alerta.call_args.args[0])

    def test_healthy_session_does_not_alert(self):
        command = RunBotCommand()
        command.stdout = StringIO()

        with (
            patch(
                f'{RUN_BOT}.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=True, jid='55119999@s.whatsapp.net'),
            ),
            patch(f'{RUN_BOT}.enviar_alerta_operador') as alerta,
        ):
            self.assertTrue(command._check_whatsapp_session())

        alerta.assert_not_called()
