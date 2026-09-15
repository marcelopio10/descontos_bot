from __future__ import annotations

from typing import Any

# `competitor_radar` (2026-08-21): oferta que chegou por link divulgado em grupo
# concorrente e resolvido pelo radar. Como as demais, é só rótulo de origem —
# nada aqui identifica grupo ou remetente, e os campos de identidade continuam
# sendo removidos em `build_sanitized_raw_payload`.
ALLOWED_SEARCH_SOURCES = frozenset({'radar_brand', 'radar_category', 'radar_price_band', 'radar_coupon_signal', 'priority_catalog', 'generic_fallback', 'competitor_radar', 'category_target', 'api_fallback'})


def sanitize_search_provenance(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {'source_kind', 'query_text', 'brand', 'category_code', 'price_band', 'marketplace'}
    result: dict[str, Any] = {}
    for key in allowed:
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        normalized_text = text.casefold()
        if (
            not text
            or len(text) > 160
            or '@g.us' in normalized_text
            or 'http://' in normalized_text
            or 'https://' in normalized_text
        ):
            continue
        if key == 'source_kind' and normalized_text not in ALLOWED_SEARCH_SOURCES:
            continue
        result[key] = normalized_text if key != 'price_band' else text
    return result


def build_sanitized_raw_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    provenance = sanitize_search_provenance(safe.get('search_provenance'))
    if provenance:
        safe['search_provenance'] = provenance
    else:
        safe.pop('search_provenance', None)
    sensitive_keys = {'raw_text', 'group_jid', 'sender_hash', 'external_message_id'}
    for key in list(safe):
        if isinstance(key, str) and key.casefold() in sensitive_keys:
            safe.pop(key, None)
    return safe
