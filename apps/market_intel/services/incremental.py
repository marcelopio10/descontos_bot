import hashlib
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.market_intel.models import (
    LearningEvent,
    MarketIntelCursor,
    MarketLearningSnapshot,
    ObservedOpportunity,
    ObservedWhatsAppMessage,
)

SOURCE = 'whatsapp'
POLICY_VERSION = '1'
TRACKING_PARAMS = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'tag', 'ref'}


def ingest_incremental_messages(*, source: str = SOURCE, lookback_hours: int = 24) -> dict[str, int]:
    """Materialize fresh observer rows into sanitized, aggregated opportunities."""
    now = timezone.now()
    cursor, _ = MarketIntelCursor.objects.get_or_create(source=source)
    messages = ObservedWhatsAppMessage.objects.all().order_by('id')
    if cursor.last_message_id:
        messages = messages.filter(id__gt=cursor.last_message_id)
    else:
        messages = messages.filter(sent_at__gte=now - timedelta(hours=lookback_hours))

    processed = 0
    for message in messages.iterator():
        _upsert_opportunity(message)
        processed += 1
        cursor.last_message_id = message.id
        cursor.last_message_sent_at = message.sent_at

    cursor.last_run_at = now
    cursor.processed_count += processed
    cursor.save(update_fields=[
        'last_message_id', 'last_message_sent_at', 'last_run_at',
        'processed_count', 'updated_at',
    ])
    return {'processed': processed, 'opportunities': ObservedOpportunity.objects.count()}


@transaction.atomic
def _upsert_opportunity(message: ObservedWhatsAppMessage) -> ObservedOpportunity:
    fingerprint = opportunity_fingerprint(message)
    category = _category(message)
    price_band = _price_band(message.parsed_price)
    defaults = {
        'marketplace': message.parsed_marketplace,
        'category': category,
        'brand': message.marca,
        'coupon': message.parsed_coupon,
        'price_band': price_band,
        'latest_price': message.parsed_price,
        'max_discount_pct': message.parsed_discount_pct,
        'first_observed_at': message.sent_at,
        'last_observed_at': message.sent_at,
        'occurrence_count': 1,
        'source_group_count': 1,
        'last_message_id': message.id,
    }
    opportunity, created = ObservedOpportunity.objects.get_or_create(
        fingerprint=fingerprint,
        defaults=defaults,
    )
    if not created:
        opportunity.last_observed_at = max(opportunity.last_observed_at, message.sent_at)
        opportunity.occurrence_count += 1
        opportunity.latest_price = message.parsed_price or opportunity.latest_price
        if message.parsed_discount_pct is not None:
            opportunity.max_discount_pct = max(
                opportunity.max_discount_pct or Decimal('0'),
                message.parsed_discount_pct,
            )
        opportunity.source_group_count = (
            ObservedWhatsAppMessage.objects.filter(
                id__in=ObservedWhatsAppMessage.objects.filter(
                    parsed_marketplace=message.parsed_marketplace,
                    parsed_coupon=message.parsed_coupon,
                ).values('id'),
            ).values('group_id').distinct().count()
        ) or opportunity.source_group_count
        opportunity.last_message_id = message.id
        opportunity.save(update_fields=[
            'last_observed_at', 'occurrence_count', 'latest_price',
            'max_discount_pct', 'source_group_count', 'last_message_id',
            'updated_at',
        ])
    LearningEvent.objects.create(
        event_type='observed_opportunity',
        key=f'{opportunity.marketplace}:{opportunity.category}:{opportunity.price_band}',
        observed_at=message.sent_at,
        payload={
            'fingerprint': fingerprint,
            'marketplace': opportunity.marketplace,
            'category': opportunity.category,
            'price_band': opportunity.price_band,
            'has_coupon': bool(opportunity.coupon),
            'freshness_minutes': max(0, int((timezone.now() - message.sent_at).total_seconds() // 60)),
        },
        policy_version=POLICY_VERSION,
    )
    return opportunity


def opportunity_fingerprint(message: ObservedWhatsAppMessage) -> str:
    urls = [_canonical_url(url) for url in (message.urls or [])]
    urls = sorted(url for url in urls if url)
    if urls:
        identity = '|'.join(urls)
    else:
        identity = '|'.join([
            message.parsed_marketplace or '',
            _category(message),
            message.marca or '',
            message.parsed_coupon or '',
            _price_band(message.parsed_price),
            _text_identity(message.text),
        ])
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def build_learning_snapshot(*, lookback_hours: int = 24) -> MarketLearningSnapshot:
    end = timezone.now()
    start = end - timedelta(hours=lookback_hours)
    events = LearningEvent.objects.filter(observed_at__gte=start, observed_at__lte=end)
    opportunities = ObservedOpportunity.objects.filter(last_observed_at__gte=start)
    category_counts = _counts(opportunities, 'category')
    marketplace_counts = _counts(opportunities, 'marketplace')
    funnel = {
        'observed_messages': events.count(),
        'observed_unique_opportunities': opportunities.count(),
        'catalog_matches': opportunities.filter(status=ObservedOpportunity.Status.MATCHED_CATALOG).count(),
        'search_candidates': opportunities.filter(status=ObservedOpportunity.Status.CANDIDATE).count(),
        'sent_deliveries': 0,
        'official_clicks': None,
        'official_conversions': None,
        'official_commission': None,
    }
    recommendations = [
        {
            'kind': 'search_priority',
            'key': category,
            'evidence': {'unique_opportunities': count},
            'confidence': _confidence(count),
            'impact_expected': 'aumentar cobertura de busca',
            'risk': 'sinal observacional; não é conversão',
            'expires_hours': 24,
            'rollback': 'remover prioridade no próximo snapshot',
        }
        for category, count in category_counts.items()
        if category
    ]
    payload = {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'funnel': funnel,
        'marketplaces': marketplace_counts,
        'categories': category_counts,
        'recommendations': recommendations,
        'data_quality': {'state': 'shadow', 'official_attribution_available': False},
    }
    snapshot = MarketLearningSnapshot.objects.create(
        period_start=start,
        period_end=end,
        state=MarketLearningSnapshot.State.SHADOW,
        sample_size=events.count(),
        payload=payload,
        policy_version=POLICY_VERSION,
    )
    return snapshot


def _category(message: ObservedWhatsAppMessage) -> str:
    return next(
        (str(h).split(':', 1)[1] for h in (message.scraper_hints or []) if str(h).startswith('categoria:')),
        '',
    )


def _price_band(value: Any) -> str:
    if value is None:
        return ''
    price = Decimal(str(value))
    if price < 50:
        return '0_50'
    if price < 100:
        return '50_100'
    if price < 250:
        return '100_250'
    if price < 500:
        return '250_500'
    return '500_plus'


def _canonical_url(url: str) -> str:
    parts = urlsplit(str(url or '').strip())
    if not parts.netloc:
        return ''
    query = [(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix('www.'), parts.path.rstrip('/'), urlencode(query), ''))


def _text_identity(text: str) -> str:
    value = re.sub(r'\s+', ' ', str(text or '').lower()).strip()
    value = re.sub(r'r\$\s*[0-9.,]+', 'r$ ', value)
    return value[:300]


def _counts(queryset, field: str) -> dict[str, int]:
    return dict(
        queryset.exclude(**{field: ''}).values(field).annotate(total=Count('id')).order_by('-total', field)[:20].values_list(field, 'total'),
    )


def _confidence(count: int) -> str:
    if count >= 10:
        return 'high'
    if count >= 3:
        return 'medium'
    return 'low'
