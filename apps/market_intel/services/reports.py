import re
from collections import Counter
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import timezone

from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage

LOCAL_TZ = ZoneInfo('America/Sao_Paulo')
ALLOWED_LABELS = {
    'urgencia',
    'prova_social',
    'cupom',
    'imagem',
    'ate_50',
    'ate_100',
    'ate_300',
    'acima_300',
}
ALLOWED_RAW_TYPES = {'conversation', 'extendedTextMessage', 'imageMessage', 'videoMessage', 'documentMessage'}
ALLOWED_HINTS = {
    'categoria:casa/cozinha',
    'categoria:moda',
    'categoria:tecnologia',
    'categoria:beleza',
    'termo:air fryer',
    'termo:cafeteira',
    'termo:fone',
    'termo:monitor',
    'termo:tenis',
    'faixa_preco:ate_100',
    'faixa_preco:ate_300',
    'faixa_preco:acima_300',
}
ALLOWED_MARKETPLACES = {'amazon', 'mercadolivre', 'shopee', 'magalu', 'aliexpress', 'desconhecido'}
URL_OR_WHATSAPP_ID_RE = re.compile(
    r'https?://\S+|www\.\S+|[A-Za-z0-9_:+.-]+@(?:g\.us|s\.whatsapp\.net|lid)',
    re.IGNORECASE,
)
COUPON_RE = re.compile(r'^[A-Z0-9_-]{3,24}$')


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
    marketplace_counts = Counter(_sanitize_marketplace(row.parsed_marketplace) for row in rows)
    group_counts = Counter(_sanitize_public_text(row.group.name) for row in rows)
    label_counts: Counter[str] = Counter()
    for row in rows:
        label_counts.update(_allowed_values(row.editorial_labels or [], ALLOWED_LABELS))
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
        hint_counts.update(_allowed_values(row.scraper_hints or [], ALLOWED_HINTS))
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        if marketplace != 'desconhecido':
            marketplace_counts[marketplace] += 1
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
    all_messages = ObservedWhatsAppMessage.objects.select_related('group').all()
    cycle_messages = all_messages.filter(sent_at__gte=report.window_start, sent_at__lte=report.window_end)
    cumulative_summary = summarize_messages(all_messages)
    cycle_summary = summarize_messages(cycle_messages)
    return {
        'version': '1.1',
        'report_type': 'incremental_market_intel',
        'generated_at': timezone.now().isoformat(),
        'date': report.date.isoformat(),
        'window': {
            'start': report.window_start.isoformat(),
            'end': report.window_end.isoformat(),
        },
        'summary': cumulative_summary,
        'cycle_summary': cycle_summary,
        'recommendations': build_recommendations(cumulative_summary),
        'cycle_recommendations': build_recommendations(cycle_summary),
        'scraper_opportunities': build_scraper_opportunities(all_messages),
        'cycle_scraper_opportunities': build_scraper_opportunities(cycle_messages),
        'analyzed_offers': build_analyzed_offers(all_messages),
        'privacy': {
            'sender_identity': 'sha256 hash only in database; omitted from report',
            'message_identity': 'Source message identifiers omitted from report',
            'group_identity': 'WhatsApp group JIDs omitted from report; group names are kept for operational analysis',
            'observed_urls': 'omitted from report; never publish third-party affiliate links',
            'raw_text': 'raw third-party copy omitted from report',
        },
    }


def build_analyzed_offers(messages: QuerySet[ObservedWhatsAppMessage]) -> list[dict]:
    rows = list(messages.order_by('-sent_at', '-id'))
    return [
        {
            'observed_at': row.sent_at.isoformat(),
            'group': _sanitize_public_text(row.group.name),
            'marketplace': _sanitize_marketplace(row.parsed_marketplace),
            'price': _decimal_to_str(row.parsed_price),
            'original_price': _decimal_to_str(row.parsed_original_price),
            'discount_pct': _decimal_to_str(row.parsed_discount_pct),
            'coupon': _sanitize_coupon(row.parsed_coupon),
            'has_coupon': bool(_sanitize_coupon(row.parsed_coupon)),
            'has_image': row.has_image,
            'raw_type': row.raw_type if row.raw_type in ALLOWED_RAW_TYPES else '',
            'labels': _allowed_values(row.editorial_labels or [], ALLOWED_LABELS),
            'scraper_hints': _allowed_values(row.scraper_hints or [], ALLOWED_HINTS),
        }
        for row in rows
    ]


def _counter_items(counter: Counter, key: str) -> list[dict]:
    return [{key: name, 'count': count} for name, count in counter.most_common(10)]


def _allowed_values(values: list, allowed: set[str]) -> list[str]:
    sanitized = []
    for value in values:
        text = str(value).strip()
        if text in allowed and text not in sanitized:
            sanitized.append(text)
    return sanitized


def _sanitize_coupon(value: str) -> str:
    coupon = str(value or '').strip().upper()
    return coupon if COUPON_RE.fullmatch(coupon) else ''


def _sanitize_marketplace(value: str) -> str:
    marketplace = str(value or '').strip().lower()
    return marketplace if marketplace in ALLOWED_MARKETPLACES else 'desconhecido'


def _sanitize_public_text(value: str, max_length: int = 120) -> str:
    text = str(value or '').strip()
    text = URL_OR_WHATSAPP_ID_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length]


def _decimal_to_str(value: Decimal | None) -> str:
    return str(value) if value is not None else ''
