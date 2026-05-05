import logging
import random
import time
from dataclasses import dataclass

from apps.curation.services.settings import get_integer_setting
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)


log = logging.getLogger(__name__)

DEFAULT_CYCLE_MIN_MINUTES = 90
DEFAULT_CYCLE_MAX_MINUTES = 180


@dataclass(frozen=True)
class SchedulerConfig:
    min_minutes: int
    max_minutes: int


def get_scheduler_config() -> SchedulerConfig:
    min_minutes = get_integer_setting(
        'cycle_min_minutes',
        DEFAULT_CYCLE_MIN_MINUTES,
    )
    max_minutes = get_integer_setting(
        'cycle_max_minutes',
        DEFAULT_CYCLE_MAX_MINUTES,
    )

    min_minutes = max(1, min_minutes)
    max_minutes = max(min_minutes, max_minutes)

    return SchedulerConfig(
        min_minutes=min_minutes,
        max_minutes=max_minutes,
    )


def calculate_next_sleep_seconds(config: SchedulerConfig | None = None) -> int:
    config = config or get_scheduler_config()
    return random.randint(config.min_minutes * 60, config.max_minutes * 60)


def sleep_between_cycles(config: SchedulerConfig | None = None) -> int:
    seconds = calculate_next_sleep_seconds(config)
    minutes = seconds / 60
    log.info('Próximo ciclo em %.1f minutos.', minutes)
    time.sleep(seconds)
    return seconds


def wait_until_distribution_window(poll_seconds: int = 60) -> None:
    while is_distribution_silenced():
        log.warning(get_silence_error_message())
        time.sleep(poll_seconds)
