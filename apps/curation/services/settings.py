from decimal import Decimal, InvalidOperation

from apps.panel.models import Setting


def get_integer_setting(key: str, default: int) -> int:
    value = _get_setting_value(key)
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_decimal_setting(key: str, default: Decimal) -> Decimal:
    value = _get_setting_value(key)
    if value is None:
        return default

    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return default


def _get_setting_value(key: str) -> str | None:
    return Setting.objects.filter(key=key).values_list('value', flat=True).first()
