from django.utils import timezone

from apps.offers.models import Offer
from apps.offers.services.normalizer import NormalizedOffer


def save_normalized_offer(normalized_offer: NormalizedOffer) -> tuple[Offer, bool]:
    now = timezone.now()
    defaults = {
        'marketplace': normalized_offer.marketplace,
        'external_id': normalized_offer.external_id,
        'title': normalized_offer.title,
        'normalized_title': normalized_offer.normalized_title,
        'current_price': normalized_offer.current_price,
        'original_price': normalized_offer.original_price,
        'discount_pct': normalized_offer.discount_pct,
        'product_url': normalized_offer.product_url,
        'affiliate_url': normalized_offer.affiliate_url,
        'asin': normalized_offer.asin,
        'price_collected_at': normalized_offer.price_collected_at or now,
        'image_url': normalized_offer.image_url,
        'is_active': True,
        'raw_payload': normalized_offer.raw_payload,
        'last_seen_at': now,
    }
    offer, created = Offer.objects.get_or_create(
        offer_hash=normalized_offer.offer_hash,
        defaults={
            **defaults,
            'first_seen_at': now,
        },
    )
    if created:
        return offer, created

    for field, value in defaults.items():
        setattr(offer, field, value)
    offer.save(update_fields=[*defaults.keys(), 'updated_at'])
    return offer, created
