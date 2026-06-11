from collections import Counter
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import timezone

from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage

LOCAL_TZ = ZoneInfo('America/Sao_Paulo')


def generate_daily_report(report_date: date) -> MarketIntelDailyReport:
    window_start = datetime.combine(report_date, time.min, tzinfo=LOCAL_TZ).astimezone(dt_timezone.utc)
    window_end = datetime.combine(report_date, time.max, tzinfo=LOCAL_TZ).astimezone(dt_timezone.utc)
    messages = ObservedWhatsAppMessage.objects.select_related('group').filter(
        sent_at__gte=window_start,
        sent_at__lte=window_end,
    )
    summary = summarize_messages(messages)
    recommendations = build_recommendations(summary)
    opportunities = build_scraper_opportunities(messages)
    report, _ = MarketIntelDailyReport.objects.update_or_create(
        date=report_date,
        defaults={
            'window_start': window_start,
            'window_end': window_end,
            'groups_analyzed': summary['groups_analyzed'],
            'messages_analyzed': summary['messages_analyzed'],
            'summary_json': summary,
            'recommendations_json': recommendations,
            'scraper_opportunities_json': opportunities,
        },
    )
    return report


def summarize_messages(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    rows = list(messages)
    marketplace_counts = Counter(row.parsed_marketplace or 'desconhecido' for row in rows)
    group_counts = Counter(row.group.name for row in rows)
    label_counts: Counter[str] = Counter()
    for row in rows:
        label_counts.update(row.editorial_labels or [])
    return {
        'groups_analyzed': len({row.group_id for row in rows}),
        'messages_analyzed': len(rows),
        'top_groups': _counter_items(group_counts, 'group'),
        'top_marketplaces': _counter_items(marketplace_counts, 'marketplace'),
        'top_labels': _counter_items(label_counts, 'label'),
        'image_messages': sum(1 for row in rows if row.has_image),
        'coupon_messages': sum(1 for row in rows if row.parsed_coupon),
    }


def build_recommendations(summary: dict) -> list[dict]:
    recommendations: list[dict] = []
    if summary.get('coupon_messages', 0):
        recommendations.append({
            'type': 'copy',
            'title': 'Destacar cupom quando existir',
            'reason': 'Grupos monitorados usam cupom como gancho editorial recorrente.',
        })
    if summary.get('image_messages', 0):
        recommendations.append({
            'type': 'creative',
            'title': 'Priorizar ofertas com imagem forte',
            'reason': 'Amostra observada contém mensagens com imagem, útil para WhatsApp e Instagram.',
        })
    recommendations.append({
        'type': 'curation',
        'title': 'Usar achados como sinais agregados, não como fonte de ofertas',
        'reason': 'Mantém compliance e evita copiar links/copy de terceiros.',
    })
    return recommendations


def build_scraper_opportunities(messages: QuerySet[ObservedWhatsAppMessage]) -> list[dict]:
    hint_counts: Counter[str] = Counter()
    marketplace_counts: Counter[str] = Counter()
    for row in messages:
        hint_counts.update(row.scraper_hints or [])
        if row.parsed_marketplace:
            marketplace_counts[row.parsed_marketplace] += 1
    opportunities = []
    for hint, count in hint_counts.most_common(10):
        opportunities.append({
            'hint': hint,
            'count': count,
            'reason': 'Recorrência nos grupos monitorados.',
        })
    for marketplace, count in marketplace_counts.most_common(5):
        opportunities.append({
            'marketplace': marketplace,
            'count': count,
            'reason': 'Marketplace aparece nos grupos monitorados e deve ser comparado com cobertura própria.',
        })
    return opportunities


def build_daily_report_payload(report: MarketIntelDailyReport) -> dict:
    return {
        'version': '1.0',
        'generated_at': timezone.now().isoformat(),
        'date': report.date.isoformat(),
        'window': {
            'start': report.window_start.isoformat(),
            'end': report.window_end.isoformat(),
        },
        'summary': report.summary_json,
        'recommendations': report.recommendations_json,
        'scraper_opportunities': report.scraper_opportunities_json,
        'privacy': {
            'sender_identity': 'sha256 hash only in database; omitted from report',
            'observed_urls': 'omitted from report; never publish third-party affiliate links',
        },
    }


def _counter_items(counter: Counter, key: str) -> list[dict]:
    return [{key: name, 'count': count} for name, count in counter.most_common(10)]
