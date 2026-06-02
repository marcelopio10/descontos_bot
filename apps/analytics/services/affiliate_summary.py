import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.analytics.models import AffiliateConversion, AffiliateSource


DEFAULT_WINDOW_DAYS = 7
TOP_OFFERS_LIMIT = 10
SUMMARY_FILENAME = 'affiliate-summary.json'


@dataclass(frozen=True)
class SummaryResult:
    output_path: str
    window_days: int
    totals: dict
    rows_by_channel: int
    rows_by_source: int
    top_offers_count: int


def publish_affiliate_summary(window_days: int = DEFAULT_WINDOW_DAYS) -> SummaryResult:
    payload = build_affiliate_summary_payload(window_days=window_days)
    output_path = Path(settings.SITE_PUBLIC_DIR) / SUMMARY_FILENAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding='utf-8',
    )
    return SummaryResult(
        output_path=str(output_path),
        window_days=window_days,
        totals=payload['totals'],
        rows_by_channel=len(payload['by_channel']),
        rows_by_source=len(payload['by_source']),
        top_offers_count=len(payload['top_offers']),
    )


def build_affiliate_summary_payload(window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    now = timezone.now()
    cutoff_date = (now - timedelta(days=window_days)).date()

    qs = AffiliateConversion.objects.filter(report_date__gte=cutoff_date)

    totals = qs.aggregate(
        clicks=Sum('clicks'),
        conversions=Sum('conversions'),
        revenue_brl=Sum('revenue_brl'),
        commission_brl=Sum('commission_brl'),
    )

    by_channel = list(
        qs.values('social_channel__code', 'social_channel__name')
        .annotate(
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
            revenue_brl=Sum('revenue_brl'),
            commission_brl=Sum('commission_brl'),
        )
        .order_by('-commission_brl')
    )

    by_source = list(
        qs.values('source')
        .annotate(
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
            revenue_brl=Sum('revenue_brl'),
            commission_brl=Sum('commission_brl'),
        )
        .order_by('-commission_brl')
    )

    top_offers = list(
        qs.values(
            'offer__slug',
            'offer__title',
            'offer__marketplace__code',
        )
        .annotate(
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
            commission_brl=Sum('commission_brl'),
        )
        .order_by('-commission_brl')[:TOP_OFFERS_LIMIT]
    )

    return {
        'generated_at': now.isoformat(),
        'window_days': window_days,
        'totals': _normalize_totals(totals),
        'by_channel': [_serialize_channel_row(row) for row in by_channel],
        'by_source': [_serialize_source_row(row) for row in by_source],
        'top_offers': [_serialize_offer_row(row) for row in top_offers],
    }


def _normalize_totals(totals: dict) -> dict:
    return {
        'clicks': int(totals.get('clicks') or 0),
        'conversions': int(totals.get('conversions') or 0),
        'revenue_brl': _decimal_str(totals.get('revenue_brl')),
        'commission_brl': _decimal_str(totals.get('commission_brl')),
    }


def _serialize_channel_row(row: dict) -> dict:
    code = row.get('social_channel__code') or 'organico'
    name = row.get('social_channel__name') or 'Orgânico / sem segmentação'
    return {
        'channel_code': code,
        'channel_name': name,
        'clicks': int(row.get('clicks') or 0),
        'conversions': int(row.get('conversions') or 0),
        'revenue_brl': _decimal_str(row.get('revenue_brl')),
        'commission_brl': _decimal_str(row.get('commission_brl')),
    }


def _serialize_source_row(row: dict) -> dict:
    source = row.get('source') or ''
    label = AffiliateSource(source).label if source in AffiliateSource.values else source
    return {
        'source': source,
        'source_label': label,
        'clicks': int(row.get('clicks') or 0),
        'conversions': int(row.get('conversions') or 0),
        'revenue_brl': _decimal_str(row.get('revenue_brl')),
        'commission_brl': _decimal_str(row.get('commission_brl')),
    }


def _serialize_offer_row(row: dict) -> dict:
    return {
        'slug': row.get('offer__slug') or '',
        'title': row.get('offer__title') or '',
        'marketplace': row.get('offer__marketplace__code') or '',
        'clicks': int(row.get('clicks') or 0),
        'conversions': int(row.get('conversions') or 0),
        'commission_brl': _decimal_str(row.get('commission_brl')),
    }


def _decimal_str(value) -> str:
    if value is None:
        return '0.00'
    return f'{Decimal(value):.2f}'


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f'Type not serializable: {type(value)}')
