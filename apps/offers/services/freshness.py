from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


DEFAULT_SITE_OFFER_MAX_AGE_HOURS = 36


def resolve_max_age_hours() -> int:
    raw = getattr(settings, 'SITE_OFFER_MAX_AGE_HOURS', DEFAULT_SITE_OFFER_MAX_AGE_HOURS)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SITE_OFFER_MAX_AGE_HOURS
    return parsed if parsed > 0 else DEFAULT_SITE_OFFER_MAX_AGE_HOURS


def get_freshness_cutoff() -> datetime:
    return timezone.now() - timedelta(hours=resolve_max_age_hours())
