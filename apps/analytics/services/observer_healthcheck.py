"""Healthcheck de supervisão do observer de WhatsApp (market intel) e dos canais.

Duas verificações independentes, cada uma disparando `apps.analytics.services.alertas`
quando o limiar é ultrapassado:

- `verificar_observer_atrasado`: o observer (`market_intel`) não coletou nenhuma
  mensagem nova há mais de `horas_limite`h — sinal de que o pipeline de coleta
  (Evolution/wa_service) parou de alimentar o `ObservedWhatsAppMessage`.
- `verificar_canais_sem_entrega`: um canal social habilitado não teve nenhuma
  entrega `SENT` registrada há mais de `horas_limite`h — sinal de que a
  distribuição parou para aquele canal especificamente.

As funções `observer_esta_atrasado` / `canais_sem_entrega_recente` fazem só a
consulta (sem alertar) e são reaproveitadas pelo `--dry-run` do comando
`check_observer_health`.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.analytics.services.alertas import alertar_canal_sem_entrega, alertar_observer_atrasado
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.execution_window import SILENCE_END
from apps.market_intel.models import ObservedWhatsAppMessage


log = logging.getLogger(__name__)

DEFAULT_STALE_HOURS = 24


def delivery_activity_cutoff(hours: int, now=None):
    """Desconta a janela de silêncio diária do tempo sem entregas."""
    cursor = timezone.localtime(now or timezone.now())
    remaining = timedelta(hours=hours)
    while remaining > timedelta(0):
        opening = cursor.replace(
            hour=SILENCE_END.hour, minute=SILENCE_END.minute,
            second=0, microsecond=0,
        )
        if cursor <= opening:
            cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
            opening = (cursor - timedelta(days=1)).replace(
                hour=SILENCE_END.hour, minute=SILENCE_END.minute,
            )
        available = cursor - opening
        if remaining <= available:
            return cursor - remaining
        remaining -= available
        cursor = opening.replace(hour=0, minute=0)
    return cursor


def observer_esta_atrasado(horas_limite: int = DEFAULT_STALE_HOURS) -> bool:
    """Só consulta: True se o observer nunca coletou ou a última coleta passou do limite."""
    limite = timezone.now() - timedelta(hours=horas_limite)
    ultima_coleta = (
        ObservedWhatsAppMessage.objects.order_by('-collected_at')
        .values_list('collected_at', flat=True)
        .first()
    )
    return ultima_coleta is None or ultima_coleta < limite


def canais_sem_entrega_recente(
    horas_limite: int = DEFAULT_STALE_HOURS,
    *,
    channel_code: str | None = None,
    active_hours: bool = False,
) -> list[str]:
    """Só consulta: códigos dos canais habilitados sem entrega SENT nas últimas `horas_limite`h."""
    limite = timezone.now() - timedelta(hours=horas_limite)
    if active_hours:
        limite = delivery_activity_cutoff(horas_limite)
    sem_entrega: list[str] = []
    channels = SocialChannel.objects.filter(is_enabled=True)
    if channel_code is not None:
        channels = channels.filter(code=channel_code)
    for channel in channels:
        tem_entrega_recente = Delivery.objects.filter(
            social_channel=channel,
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=limite,
        ).exists()
        if not tem_entrega_recente:
            sem_entrega.append(channel.code)
    return sem_entrega


def verificar_observer_atrasado(horas_limite: int = DEFAULT_STALE_HOURS) -> bool:
    """Verifica e, se atrasado, dispara `alertar_observer_atrasado`. Retorna True se alertou."""
    if not observer_esta_atrasado(horas_limite):
        return False
    log.error('observer_healthcheck.atrasado horas_limite=%s', horas_limite)
    alertar_observer_atrasado(horas_limite)
    return True


def verificar_canais_sem_entrega(
    horas_limite: int = DEFAULT_STALE_HOURS,
    *,
    channel_code: str | None = None,
    active_hours: bool = False,
) -> list[str]:
    """Verifica e, para cada canal sem entrega recente, dispara `alertar_canal_sem_entrega`.

    Retorna a lista de códigos de canal para os quais o alerta foi disparado.
    """
    canais_alertados = canais_sem_entrega_recente(
        horas_limite, channel_code=channel_code, active_hours=active_hours,
    )
    for channel_code in canais_alertados:
        log.error(
            'observer_healthcheck.canal_sem_entrega channel=%s horas_limite=%s',
            channel_code, horas_limite,
        )
        if active_hours:
            alertar_canal_sem_entrega(channel_code, horas_limite, active_hours=True)
        else:
            alertar_canal_sem_entrega(channel_code, horas_limite)
    return canais_alertados
