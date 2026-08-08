from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from apps.analytics.services.link_builder import _append_utm_params


def build_coupon_link(candidate, channel) -> str:
    base = candidate.affiliate_url or candidate.destination_url or candidate.campaign_url
    if not base:
        return ''
    return _append_utm_params(base, utm_source='whatsapp' if channel.channel_type.startswith('whatsapp') else 'telegram', utm_medium='coupon', utm_campaign=f'coupon_{candidate.candidate_hash[:12]}')
