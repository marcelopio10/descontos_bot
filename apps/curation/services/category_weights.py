from typing import TYPE_CHECKING

from apps.curation.services.settings import get_json_setting


if TYPE_CHECKING:
    from apps.offers.models import Category


SETTING_KEY = 'category_weights'
MIN_WEIGHT = 1
MAX_WEIGHT = 10
DEFAULT_WEIGHT = 5


def resolve_category_weight(category: 'Category | None') -> int:
    if category is None:
        return DEFAULT_WEIGHT

    override = _get_overrides().get(category.code)
    if override is not None:
        return _clamp(override)

    return _clamp(category.weight or DEFAULT_WEIGHT)


def get_all_weights() -> dict[str, int]:
    from apps.offers.models import Category

    overrides = _get_overrides()
    result: dict[str, int] = {}
    for category in Category.objects.filter(is_active=True):
        if category.code in overrides:
            result[category.code] = _clamp(overrides[category.code])
        else:
            result[category.code] = _clamp(category.weight or DEFAULT_WEIGHT)
    return result


def get_override_map() -> dict[str, int]:
    return {code: _clamp(value) for code, value in _get_overrides().items()}


def _get_overrides() -> dict[str, int]:
    raw = get_json_setting(SETTING_KEY, {})
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, int] = {}
    for code, value in raw.items():
        try:
            parsed[str(code)] = int(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _clamp(value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT
    return max(MIN_WEIGHT, min(MAX_WEIGHT, n))
