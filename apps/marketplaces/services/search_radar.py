from __future__ import annotations

from typing import Any

from apps.curation.services.observer_context import build_observer_context

SEARCH_BRANDS = {
    'moda': ('insider', 'nike', 'adidas', 'puma', 'mizuno', 'asics', 'new balance', 'olympikus', 'fila', 'lupo', 'oakley', 'under armour'),
    'perfumes_arabes': ('lattafa', 'afnan', 'armaf', 'rasasi', 'al haramain', 'maison alhambra', 'swiss arabian', 'khadlaj', 'fragrance world', 'paris corner', 'asdaaf', 'ajmal', 'al wataniah', 'ard al zaafaran'),
    'suplementos': ('growth', 'max titanium', 'dark lab', 'integralmedica', 'vitafor', 'dux nutrition', 'adaptogen', 'soldiers nutrition', 'atlhetica nutrition', 'bodyaction', 'probiótica', 'essential nutrition', 'nutrify', 'optimum nutrition', 'universal nutrition', 'muscletech', 'black skull'),
    'tecnologia': ('samsung', 'lg', 'xiaomi', 'motorola', 'jbl', 'sony', 'logitech', 'acer', 'lenovo', 'apple'),
    'casa': ('electrolux', 'brastemp', 'consul', 'mondial', 'oster', 'arno', 'tramontina', 'philips walita', 'wap', 'kärcher'),
}


def build_search_radar(*, lookback_hours: int = 168, limit: int = 30) -> dict[str, Any]:
    context = build_observer_context(lookback_hours=lookback_hours, limit=limit)
    radar = context.get('opportunity_radar') or {}
    observed = {str(item).lower(): count for bucket in ('brands', 'categories', 'marketplaces', 'price_bands') for item, count in (radar.get(bucket) or {}).items()}
    brands = []
    for family, values in SEARCH_BRANDS.items():
        for brand in values:
            brands.append({'family': family, 'term': brand, 'observed_count': int(observed.get(brand.lower(), 0))})
    brands.sort(key=lambda row: (-row['observed_count'], row['family'], row['term']))
    return {
        'lookback_hours': lookback_hours,
        'brands': brands[:limit],
        'categories': radar.get('categories', {}),
        'marketplaces': radar.get('marketplaces', {}),
        'price_bands': radar.get('price_bands', {}),
        'coupon_signals': {key: value for key, value in (radar.get('coupons') or {}).items() if key.upper() != 'CUPOM'},
        'generic_coupon_prevalence': int((radar.get('coupons') or {}).get('CUPOM', 0)),
        'source': 'sanitized_observer_aggregate',
    }
