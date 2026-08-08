from __future__ import annotations

from apps.curation.services.observer_context import build_observer_context


def build_coupon_editorial_pattern(observer_context: dict | None = None) -> dict:
    context = observer_context or build_observer_context(lookback_hours=168, limit=12)
    labels = context.get('editorial_label_counts', {})
    radar = context.get('opportunity_radar', {})
    return {
        'observed_message_count': context.get('messages_analyzed', 0),
        'coupon_signal_count': sum(radar.get('coupons', {}).values()),
        'common_cta_terms': labels.get('cta', labels.get('cta_terms', {})),
        'recommended_order': ['benefit', 'activation_code', 'restrictions', 'validity', 'cta'],
        'style': 'direto, benefício antes do código, urgência somente quando comprovada',
        'source': 'observer agregado e sanitizado',
    }
