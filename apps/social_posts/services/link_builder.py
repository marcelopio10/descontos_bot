from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from apps.offers.models import Offer


def build_instagram_tracked_url(
    offer: Offer,
    medium: str,
    content: str = '',
) -> str:
    base_url = offer.affiliate_link
    query = dict(parse_qsl(urlsplit(base_url).query, keep_blank_values=True))
    query.update(
        {
            'utm_source': 'instagram',
            'utm_medium': medium,
            'utm_campaign': f'offer_{offer.id}',
        },
    )
    if content:
        query['utm_content'] = content

    parts = urlsplit(base_url)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        ),
    )
