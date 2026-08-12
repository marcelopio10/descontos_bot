from __future__ import annotations

from typing import Any

ALLOWED_SEARCH_SOURCES = frozenset({'radar_brand', 'radar_category', 'radar_price_band', 'radar_coupon_signal', 'priority_catalog', 'generic_fallback'})
MAX_PROVENANCE_HISTORY = 8


def sanitize_search_provenance(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        'source_kind', 'query_text', 'brand', 'category_code', 'price_band',
        'marketplace', 'opportunity_id', 'query_hash',
    }
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


def merge_sanitized_raw_payload(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    """Preserva a origem atual e um histórico curto ao atualizar uma oferta."""
    merged = build_sanitized_raw_payload(current or {})
    old = build_sanitized_raw_payload(previous or {})
    current_provenance = merged.get('search_provenance')
    history = list(old.get('search_provenance_history') or [])
    old_provenance = old.get('search_provenance')
    if isinstance(old_provenance, dict) and old_provenance != current_provenance:
        history.append(old_provenance)
    if isinstance(current_provenance, dict):
        history.append(current_provenance)
    deduped = []
    for item in history:
        if item not in deduped:
            deduped.append(item)
    if deduped:
        merged['search_provenance_history'] = deduped[-MAX_PROVENANCE_HISTORY:]
    return merged
