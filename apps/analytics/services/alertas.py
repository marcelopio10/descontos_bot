"""Alertas operacionais via Telegram do operador.

Centraliza o disparo de notificações para o operador humano quando algo no
pipeline (scraping, curadoria, entrega, observer) precisa de atenção.

Reusa o MESMO bot/chat já configurado para o handoff do Instagram
(`INSTAGRAM_HANDOFF_BOT_TOKEN`/`INSTAGRAM_HANDOFF_CHAT_ID`, ver
`apps.social_posts.services.instagram_handoff_telegram`), com nomes
`OPERATOR_ALERT_BOT_TOKEN`/`OPERATOR_ALERT_CHAT_ID` como alias preferencial
(fallback automático para as variáveis do handoff) — não é necessário criar
nenhuma credencial nova.

Nenhuma função aqui lança exceção: alertas não podem derrubar o processo
principal (scraper, curadoria etc.). Falhas de envio/configuração apenas
geram `log.warning`.
"""

import logging
from html import escape

from django.conf import settings

from apps.distribution.services.telegram_client import TelegramClient, TelegramClientError


log = logging.getLogger(__name__)


def enviar_alerta_operador(mensagem: str, categoria: str = '') -> None:
    """Envia um alerta operacional para o Telegram do operador.

    Se as credenciais não estiverem configuradas, ou se o envio falhar por
    qualquer motivo, apenas loga um warning — nunca lança exceção.
    """
    token = _resolve_setting('OPERATOR_ALERT_BOT_TOKEN', 'INSTAGRAM_HANDOFF_BOT_TOKEN')
    chat_id = _resolve_setting('OPERATOR_ALERT_CHAT_ID', 'INSTAGRAM_HANDOFF_CHAT_ID')

    if not token or not chat_id:
        log.warning(
            'alertas.nao_configurado categoria=%s mensagem=%s',
            categoria or '(sem categoria)', mensagem,
        )
        return

    # A API do Telegram recebe isto em parse_mode HTML: qualquer '<' vindo do
    # dado (um `<N>` de instrução, um `<html>` de mensagem de erro, um '&' em
    # título de produto) derruba a mensagem inteira com HTTP 400 e o alerta some
    # em silêncio — justamente quando havia algo a avisar. Nenhum caller manda
    # markup; a marcação é a daqui.
    prefixo = f'[{escape(categoria)}] ' if categoria else ''
    texto_html = f'⚠️ <b>Alerta operacional</b>\n{prefixo}{escape(mensagem)}'

    try:
        client = TelegramClient(token=token)
        result = client.send_message(chat_id=chat_id, text_html=texto_html)
    except TelegramClientError as exc:
        log.warning('alertas.envio_falhou categoria=%s error=%s', categoria, exc)
        return
    except Exception:  # pragma: no cover - defensive boundary, nunca deve derrubar o caller
        log.exception('alertas.envio_falhou_inesperado categoria=%s', categoria)
        return

    if not result.success:
        log.warning(
            'alertas.envio_falhou categoria=%s error=%s',
            categoria, result.error_message,
        )
    else:
        log.info('alertas.enviado categoria=%s message_id=%s', categoria, result.message_id)


def alertar_scraper_zero_ofertas(marketplace_code: str, run_id: int | None, detalhe: str) -> None:
    """Dispara quando um ciclo de scraping termina com 0 ofertas válidas (ou bloqueado)."""
    enviar_alerta_operador(
        f'Scraper "{marketplace_code}" (run #{run_id}) terminou sem ofertas válidas. {detalhe}'.strip(),
        categoria='scraper_zero_ofertas',
    )


def alertar_curadoria_falhas_consecutivas(channel_code: str, run_id: int | None, total_falhas: int) -> None:
    """Dispara quando 2+ execuções seguidas de `CurationRun` falham para o mesmo canal."""
    enviar_alerta_operador(
        f'Curadoria IA: {total_falhas} execuções seguidas com status FAILED no canal '
        f'"{channel_code}" (última: run #{run_id}).',
        categoria='curadoria_falhas_consecutivas',
    )


def alertar_canal_sem_entrega(channel_code: str, horas: int) -> None:
    """Dispara quando um canal habilitado fica mais de `horas`h sem nenhuma entrega enviada."""
    enviar_alerta_operador(
        f'Canal "{channel_code}" está há mais de {horas}h sem nenhuma entrega enviada.',
        categoria='canal_sem_entrega',
    )


def alertar_observer_atrasado(horas: int) -> None:
    """Dispara quando o observer de WhatsApp (market intel) fica mais de `horas`h sem coletar mensagem nova."""
    enviar_alerta_operador(
        f'Observer de WhatsApp (market intel) está há mais de {horas}h sem coletar mensagem nova.',
        categoria='observer_atrasado',
    )


def _resolve_setting(preferred_name: str, fallback_name: str) -> str:
    value = getattr(settings, preferred_name, '')
    if value:
        return value
    return getattr(settings, fallback_name, '')
