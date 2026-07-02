from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage

SENSITIVE_KEYS = {'jid', 'group_jid', 'sender_hash', 'text', 'urls', 'raw_text', 'message_id', 'external_message_id'}


def build_observer_context(*, lookback_hours: int = 24, limit: int = 20) -> dict[str, Any]:
    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    messages = ObservedWhatsAppMessage.objects.filter(sent_at__gte=cutoff)
    marketplace_counts = dict(
        messages.exclude(parsed_marketplace='')
        .values_list('parsed_marketplace')
        .annotate(total=Count('id'))
        .order_by('-total')[:limit]
    )
    labels = _top_json_list_values(messages, 'editorial_labels', limit=limit)
    recent_report = MarketIntelDailyReport.objects.order_by('-date').first()
    context = {
        'lookback_hours': lookback_hours,
        'messages_analyzed': messages.count(),
        'marketplace_counts': marketplace_counts,
        'editorial_label_counts': labels,
        'latest_report': _sanitize_latest_report(recent_report),
    }
    return assert_sanitized_context(context)


def assert_sanitized_context(context: dict[str, Any]) -> dict[str, Any]:
    _walk_for_sensitive_data(context)
    return context


def _sanitize_latest_report(report: MarketIntelDailyReport | None) -> dict[str, Any]:
    if report is None:
        return {}
    summary = report.summary_json or {}
    return {
        'date': report.date.isoformat(),
        'payload_version': report.payload_version,
        'messages_analyzed': report.messages_analyzed,
        'groups_analyzed': report.groups_analyzed,
        'summary': _drop_sensitive(summary),
    }


def _top_json_list_values(queryset, field: str, *, limit: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for values in queryset.values_list(field, flat=True):
        if not isinstance(values, list):
            continue
        for value in values:
            key = str(value or '').strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit])


def _drop_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            key_s = str(key)
            if key_s in SENSITIVE_KEYS or key_s.endswith('_jid') or 'url' in key_s.lower():
                continue
            cleaned[key_s] = _drop_sensitive(nested)
        return cleaned
    if isinstance(value, list):
        return [_drop_sensitive(item) for item in value]
    if isinstance(value, str) and ('http://' in value or 'https://' in value or '@g.us' in value):
        return '[redacted]'
    return value


def _walk_for_sensitive_data(value: Any, path: str = '$') -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_s = str(key)
            if key_s in SENSITIVE_KEYS or key_s.endswith('_jid'):
                raise ValueError(f'contexto observer contém chave sensível: {path}.{key_s}')
            _walk_for_sensitive_data(nested, f'{path}.{key_s}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_for_sensitive_data(item, f'{path}[{index}]')
    elif isinstance(value, str):
        if '@g.us' in value or 'http://' in value or 'https://' in value:
            raise ValueError(f'contexto observer contém valor sensível em {path}')
