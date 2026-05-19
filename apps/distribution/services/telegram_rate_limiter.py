import threading
import time

from django.conf import settings


GLOBAL_RATE_PER_SECOND = 30


class TelegramRateLimiter:
    def __init__(self, per_chat_seconds: float | None = None):
        self._lock = threading.Lock()
        self._last_sent_at: dict[str, float] = {}
        self._global_window: list[float] = []
        self._per_chat_seconds = (
            per_chat_seconds
            if per_chat_seconds is not None
            else float(getattr(settings, 'TELEGRAM_RATE_LIMIT_SECONDS', 1.1))
        )

    def wait_for_send(self, chat_id: str) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                wait_chat = self._chat_wait(chat_id, now)
                wait_global = self._global_wait(now)
                wait = max(wait_chat, wait_global)
                if wait <= 0:
                    self._last_sent_at[chat_id] = now
                    self._global_window.append(now)
                    return
            time.sleep(wait)

    def _chat_wait(self, chat_id: str, now: float) -> float:
        last = self._last_sent_at.get(chat_id)
        if last is None:
            return 0.0
        return max(0.0, (last + self._per_chat_seconds) - now)

    def _global_wait(self, now: float) -> float:
        cutoff = now - 1.0
        self._global_window = [t for t in self._global_window if t > cutoff]
        if len(self._global_window) < GLOBAL_RATE_PER_SECOND:
            return 0.0
        oldest = self._global_window[0]
        return max(0.0, (oldest + 1.0) - now)


_default_limiter: TelegramRateLimiter | None = None


def get_default_limiter() -> TelegramRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = TelegramRateLimiter()
    return _default_limiter
