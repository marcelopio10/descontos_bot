from __future__ import annotations

from typing import Any

# `competitor_radar` (2026-08-21): oferta que chegou por link divulgado em grupo
# concorrente e resolvido pelo radar. Como as demais, é só rótulo de origem —
# nada aqui identifica grupo ou remetente, e os campos de identidade continuam
# sendo removidos em `build_sanitized_raw_payload`.
ALLOWED_SEARCH_SOURCES = frozenset({'radar_brand', 'radar_category', 'radar_price_band', 'radar_coupon_signal', 'priority_catalog', 'generic_fallback', 'competitor_radar'})


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
        if not text or len(text) > 160 or '@g.us' in text or 'http://' in text or 'https://' in text:
            continue
        if key == 'source_kind' and text not in ALLOWED_SEARCH_SOURCES:
            continue
        result[key] = text.lower() if key not in {'source_kind', 'price_band'} else text
    return result


def build_sanitized_raw_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload or {})
    provenance = sanitize_search_provenance(safe.get('search_provenance'))
    if provenance:
        safe['search_provenance'] = provenance
    else:
        safe.pop('search_provenance', None)
    for key in ('raw_text', 'group_jid', 'sender_hash', 'external_message_id'):
        safe.pop(key, None)
    return safe
