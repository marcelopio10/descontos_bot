import json
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.panel.models import Setting


_TRUTHY_VALUES = {'1', 'true', 'yes', 'on'}


def get_bool_setting(key: str, default: bool) -> bool:
    """Lê uma Setting booleana. Valores aceitos como verdadeiro (case-insensitive,
    com espaços ignorados): "1", "true", "yes", "on". Qualquer outro valor
    presente é tratado como falso. Ausência da Setting retorna `default`.
    """
    value = _get_setting_value(key)
    if value is None:
        return default

    return value.strip().lower() in _TRUTHY_VALUES


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


def get_json_setting(key: str, default: Any) -> Any:
    value = _get_setting_value(key)
    if value is None:
        return default

    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _get_setting_value(key: str) -> str | None:
    return Setting.objects.filter(key=key).values_list('value', flat=True).first()
