from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
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
    opportunity_radar = _build_opportunity_radar(messages, limit=limit)
    recent_report = MarketIntelDailyReport.objects.order_by('-date').first()
    context = {
        'lookback_hours': lookback_hours,
        'messages_analyzed': messages.count(),
        'marketplace_counts': marketplace_counts,
        'editorial_label_counts': labels,
        'opportunity_radar': opportunity_radar,
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


def _build_opportunity_radar(queryset, *, limit: int) -> dict[str, Any]:
    """Converte observações em sinais de busca, sem copiar texto/links.

    O radar é deliberadamente agregado: marca, cupom, categoria, marketplace e
    faixa de preço. Ele serve para orientar captura/curadoria, não para afirmar
    conversão ou equivalência entre ofertas.
    """
    counts: dict[str, dict[str, int]] = {
        'brands': {},
        'coupons': {},
        'categories': {},
        'marketplaces': {},
        'price_bands': {},
    }
    for row in queryset.values(
        'marca',
        'parsed_coupon',
        'parsed_marketplace',
        'parsed_price',
        'scraper_hints',
    ):
        _increment(counts['brands'], row.get('marca'))
        _increment(counts['coupons'], row.get('parsed_coupon'))
        _increment(counts['marketplaces'], row.get('parsed_marketplace'))
        hints = row.get('scraper_hints') or []
        if isinstance(hints, list):
            _increment(counts['categories'], hints[0] if hints else None)
        _increment(counts['price_bands'], _price_band(row.get('parsed_price')))

    for key in counts:
        counts[key] = _rank_counts(counts[key], limit=limit)

    opportunities: list[dict[str, Any]] = []
    kind_order = ('brands', 'coupons', 'categories', 'price_bands', 'marketplaces')
    kind_labels = {
        'brands': 'brand',
        'coupons': 'coupon',
        'categories': 'category',
        'price_bands': 'price_band',
        'marketplaces': 'marketplace',
    }
    for bucket in kind_order:
        for key, count in counts[bucket].items():
            opportunities.append({'kind': kind_labels[bucket], 'key': key, 'count': count})
    opportunities.sort(key=lambda item: (-item['count'], kind_order.index(_bucket_for_kind(item['kind'])), item['key']))
    return {**counts, 'opportunities': opportunities[:limit]}


def _bucket_for_kind(kind: str) -> str:
    return {
        'brand': 'brands',
        'coupon': 'coupons',
        'category': 'categories',
        'price_band': 'price_bands',
        'marketplace': 'marketplaces',
    }[kind]


def _increment(bucket: dict[str, int], value: Any) -> None:
    key = str(value or '').strip()
    if key:
        bucket[key] = bucket.get(key, 0) + 1


def _rank_counts(counts: dict[str, int], *, limit: int) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:limit])


def _price_band(value: Any) -> str:
    try:
        price = Decimal(str(value))
    except Exception:
        return ''
    if price < 50:
        return '0_50'
    if price < 100:
        return '50_100'
    if price < 250:
        return '100_250'
    if price < 500:
        return '250_500'
    return '500_plus'


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
