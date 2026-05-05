from datetime import time

from django.utils import timezone


SILENCE_START = time(0, 0)
SILENCE_END = time(6, 0)


def is_distribution_silenced() -> bool:
    now = timezone.localtime()
    return SILENCE_START <= now.time() < SILENCE_END


def get_silence_error_message() -> str:
    return 'Distribuição bloqueada pela janela de silêncio 00:00-06:00 BRT.'
