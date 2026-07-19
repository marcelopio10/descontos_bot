import logging
import threading
import time
from decimal import Decimal

from apps.curation.services.settings import get_decimal_setting, get_integer_setting


log = logging.getLogger(__name__)

# Intervalo mínimo padrão entre envios consecutivos no WhatsApp (mesmo destino).
# Configurável via Setting 'wa_min_interval_seconds'. Faixa sugerida: 8-15s.
DEFAULT_WA_MIN_INTERVAL_SECONDS = Decimal('10')

# Teto opcional de envios por hora por destino. 0 desativa o teto (padrão).
# Configurável via Setting 'wa_max_sends_per_hour'.
DEFAULT_WA_MAX_SENDS_PER_HOUR = 0


class WhatsAppRateLimiter:
    """Garante um intervalo mínimo entre envios consecutivos no WhatsApp.

    Espelha o design do `TelegramRateLimiter` (por-chat + janela), mas o
    WhatsApp aqui é single-target por canal (um grupo por vez), então não há
    necessidade de um limite "global entre chats" como no Telegram — apenas o
    intervalo mínimo por destino e, opcionalmente, um teto de envios por hora.

    O `run_bot` processa o loop de entrega de forma sequencial (um envio por
    vez, sem threads), então o lock abaixo é uma proteção barata para uso
    concorrente futuro — não é o caminho crítico hoje.
    """

    def __init__(
        self,
        min_interval_seconds: float | None = None,
        max_sends_per_hour: int | None = None,
    ):
        self._lock = threading.Lock()
        self._last_sent_at: dict[str, float] = {}
        self._hourly_window: dict[str, list[float]] = {}
        self._min_interval_seconds = (
            float(min_interval_seconds)
            if min_interval_seconds is not None
            else float(
                get_decimal_setting('wa_min_interval_seconds', DEFAULT_WA_MIN_INTERVAL_SECONDS),
            )
        )
        self._max_sends_per_hour = (
            max_sends_per_hour
            if max_sends_per_hour is not None
            else get_integer_setting('wa_max_sends_per_hour', DEFAULT_WA_MAX_SENDS_PER_HOUR)
        )

    def wait_for_send(self, destination: str) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                wait_interval = self._interval_wait(destination, now)
                wait_hourly = self._hourly_wait(destination, now)
                wait = max(wait_interval, wait_hourly)
                if wait <= 0:
                    self._last_sent_at[destination] = now
                    self._hourly_window.setdefault(destination, []).append(now)
                    return
            log.info(
                'whatsapp_rate_limiter.wait destino=%s espera_segundos=%.1f',
                destination, wait,
            )
            time.sleep(wait)

    def _interval_wait(self, destination: str, now: float) -> float:
        last = self._last_sent_at.get(destination)
        if last is None:
            return 0.0
        return max(0.0, (last + self._min_interval_seconds) - now)

    def _hourly_wait(self, destination: str, now: float) -> float:
        if self._max_sends_per_hour <= 0:
            return 0.0
        cutoff = now - 3600.0
        window = [t for t in self._hourly_window.get(destination, []) if t > cutoff]
        self._hourly_window[destination] = window
        if len(window) < self._max_sends_per_hour:
            return 0.0
        oldest = window[0]
        return max(0.0, (oldest + 3600.0) - now)


_default_limiter: WhatsAppRateLimiter | None = None


def get_default_limiter() -> WhatsAppRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = WhatsAppRateLimiter()
    return _default_limiter
