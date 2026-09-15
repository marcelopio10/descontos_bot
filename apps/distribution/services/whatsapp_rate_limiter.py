import logging
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import OperationalError, transaction
from django.utils import timezone

from apps.curation.services.settings import get_decimal_setting, get_integer_setting
from apps.distribution.models import WhatsAppThrottleState


log = logging.getLogger(__name__)

# Intervalo mínimo padrão entre envios consecutivos no WhatsApp (mesmo destino).
# Configurável via Setting 'wa_min_interval_seconds'. Faixa sugerida: 8-15s.
DEFAULT_WA_MIN_INTERVAL_SECONDS = Decimal('15')

# Teto de envios por hora por destino. O limite nunca pode ser desativado.
# Configurável via Setting 'wa_max_sends_per_hour'.
DEFAULT_WA_MAX_SENDS_PER_HOUR = 20
LOCK_RETRY_LIMIT = 5
LOCK_RETRY_SLEEP_SECONDS = 0.05


class WhatsAppRateLimiter:
    """Reserva slots persistentes de envio por destino no SQLite."""

    def __init__(
        self,
        min_interval_seconds: float | None = None,
        max_sends_per_hour: int | None = None,
    ):
        configured_interval = (
            min_interval_seconds
            if min_interval_seconds is not None
            else get_decimal_setting(
                'wa_min_interval_seconds',
                DEFAULT_WA_MIN_INTERVAL_SECONDS,
            )
        )
        self._min_interval_seconds = self._safe_interval(configured_interval)
        configured_limit = (
            max_sends_per_hour
            if max_sends_per_hour is not None
            else get_integer_setting(
                'wa_max_sends_per_hour',
                DEFAULT_WA_MAX_SENDS_PER_HOUR,
            )
        )
        try:
            normalized_limit = int(configured_limit)
        except (TypeError, ValueError):
            normalized_limit = DEFAULT_WA_MAX_SENDS_PER_HOUR
        self._max_sends_per_hour = max(1, normalized_limit)

    def wait_for_send(self, destination: str) -> None:
        while True:
            wait = self._try_reserve_slot(destination)
            if wait <= 0:
                return
            log.info('whatsapp_rate_limiter.wait segundos=%.1f', wait)
            time.sleep(wait)

    def _try_reserve_slot(self, destination: str) -> float:
        destination = self._validate_destination(destination)
        for attempt in range(LOCK_RETRY_LIMIT):
            try:
                return self._try_reserve_slot_once(destination)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower() or attempt == LOCK_RETRY_LIMIT - 1:
                    raise
                time.sleep(LOCK_RETRY_SLEEP_SECONDS * (attempt + 1))
        raise RuntimeError('Falha inesperada ao reservar cadência do WhatsApp.')

    def _try_reserve_slot_once(self, destination: str) -> float:
        with transaction.atomic():
            state, created = WhatsAppThrottleState.objects.get_or_create(
                destination=destination,
            )
            if not created:
                state = WhatsAppThrottleState.objects.select_for_update().get(pk=state.pk)
                # SQLite só adquire o lock de escrita quando há uma escrita.
                state.save(update_fields=['updated_at'])
                state = WhatsAppThrottleState.objects.select_for_update().get(pk=state.pk)

            now = timezone.now()
            window_started_at = state.window_started_at
            window_count = state.window_count
            if (
                window_started_at is None
                or now >= window_started_at + timedelta(hours=1)
            ):
                window_started_at = now
                window_count = 0

            wait_interval = 0.0
            if state.last_reserved_at is not None:
                due_at = state.last_reserved_at + timedelta(
                    seconds=float(self._min_interval_seconds),
                )
                wait_interval = max(0.0, (due_at - now).total_seconds())

            wait_hourly = 0.0
            if window_count >= self._max_sends_per_hour:
                due_at = window_started_at + timedelta(hours=1)
                wait_hourly = max(0.0, (due_at - now).total_seconds())

            wait_seconds = max(wait_interval, wait_hourly)
            if wait_seconds > 0:
                if (
                    state.window_started_at != window_started_at
                    or state.window_count != window_count
                ):
                    state.window_started_at = window_started_at
                    state.window_count = window_count
                    state.save(update_fields=[
                        'window_started_at',
                        'window_count',
                        'updated_at',
                    ])
                return wait_seconds

            state.window_started_at = window_started_at
            state.window_count = window_count + 1
            state.last_reserved_at = now
            state.save(update_fields=[
                'window_started_at',
                'window_count',
                'last_reserved_at',
                'updated_at',
            ])
            return 0.0

    @staticmethod
    def _safe_interval(value: object) -> Decimal:
        try:
            interval = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return DEFAULT_WA_MIN_INTERVAL_SECONDS
        if not interval.is_finite() or interval < 0:
            return DEFAULT_WA_MIN_INTERVAL_SECONDS
        return interval

    @staticmethod
    def _validate_destination(destination: object) -> str:
        if not isinstance(destination, str):
            raise ValueError('Destino do WhatsApp deve ser texto.')
        normalized = destination.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError('Destino do WhatsApp inválido.')
        return normalized


_default_limiter: WhatsAppRateLimiter | None = None


def get_default_limiter() -> WhatsAppRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = WhatsAppRateLimiter()
    return _default_limiter
