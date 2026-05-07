import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.offers.models import Offer
from apps.offers.services.site_publisher import DISCLOSURE
from apps.social_posts.services.link_builder import build_instagram_tracked_url


@dataclass(frozen=True)
class BioLinksResult:
    output_path: Path
    items_count: int


def publish_bio_links(output_path: str | Path, count: int = 5) -> BioLinksResult:
    offers = _get_ranked_offers(count)
    payload = {
        'version': '1.0',
        'generated_at': timezone.now().isoformat(),
        'disclosure': DISCLOSURE,
        'items': [_serialize_offer(offer) for offer in offers],
    }
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return BioLinksResult(output_path=target_path, items_count=len(payload['items']))


def _get_ranked_offers(limit: int) -> list[Offer]:
    offers = list(
        Offer.objects
        .select_related('marketplace')
        .filter(is_active=True, slug__isnull=False)
        .filter(marketplace__code='amazon')
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
        .order_by('-discount_pct', 'current_price', 'title')[:limit],
    )
    if len(offers) < limit:
        raise ValueError(
            f'Ofertas publicáveis insuficientes: {len(offers)} de {limit}.',
        )
    return offers


def _serialize_offer(offer: Offer) -> dict[str, Any]:
    return {
        'id': offer.id,
        'title': offer.title,
        'current_price': str(offer.current_price),
        'discount_pct': str(offer.discount_pct or ''),
        'tracked_url': build_instagram_tracked_url(offer, 'bio'),
    }
