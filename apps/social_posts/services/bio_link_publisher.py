import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.offers.models import Offer
from apps.offers.services.freshness import get_freshness_cutoff
from apps.offers.services.site_publisher import DISCLOSURE
from apps.social_posts.services.link_builder import build_instagram_tracked_url


@dataclass(frozen=True)
class BioLinksResult:
    output_path: Path
    items_count: int


def build_links_payload(count: int = 5) -> dict[str, Any]:
    offers = _get_ranked_offers(count)
    return {
        'version': '1.1',
        'generated_at': timezone.now().isoformat(),
        'disclosure': DISCLOSURE,
        'items': [_serialize_offer(offer) for offer in offers],
    }


def publish_bio_links(output_path: str | Path, count: int = 5) -> BioLinksResult:
    payload = build_links_payload(count=count)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return BioLinksResult(output_path=target_path, items_count=len(payload['items']))


def _get_ranked_offers(limit: int) -> list[Offer]:
    cutoff = get_freshness_cutoff()
    offers = list(
        Offer.objects
        .select_related('marketplace')
        .filter(is_active=True, slug__isnull=False)
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
        .filter(discount_pct__gt=0)
        .filter(last_seen_at__gte=cutoff)
        .order_by('-discount_pct', 'current_price', 'title')[:limit],
    )
    if not offers:
        raise ValueError('Nenhuma oferta publicável dentro da janela de recência.')
    return offers


def _serialize_offer(offer: Offer) -> dict[str, Any]:
    return {
        'id': offer.id,
        'title': offer.title,
        'current_price': str(offer.current_price),
        'original_price': str(offer.original_price) if offer.original_price else '',
        'discount_pct': str(offer.discount_pct or ''),
        'image_url': offer.image_url or '',
        'marketplace_code': offer.marketplace.code,
        'tracked_url': build_instagram_tracked_url(offer, 'bio'),
    }
