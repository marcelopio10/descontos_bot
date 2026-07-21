import logging

from django.utils import timezone
from django.utils.text import slugify

from apps.offers.models import Offer
from apps.offers.services.normalizer import NormalizedOffer


log = logging.getLogger(__name__)

MAX_SLUG_LENGTH = 220
MAX_SLUG_BASE_LENGTH = 200


def save_normalized_offer(normalized_offer: NormalizedOffer) -> tuple[Offer, bool]:
    now = timezone.now()
    defaults = {
        'marketplace': normalized_offer.marketplace,
        'external_id': normalized_offer.external_id,
        'title': normalized_offer.title,
        'normalized_title': normalized_offer.normalized_title,
        'produto_canonico_id': normalized_offer.produto_canonico_id,
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
        'review_rating': normalized_offer.review_rating,
        'review_count': normalized_offer.review_count,
        'last_seen_at': now,
        'category_source': '',
    }
    offer, created = Offer.objects.get_or_create(
        offer_hash=normalized_offer.offer_hash,
        defaults={
            **defaults,
            'first_seen_at': now,
        },
    )
    if created:
        _ensure_public_slug(offer)
        _classify(offer)
        return offer, created

    update_fields = [*defaults.keys(), 'updated_at']
    for field, value in defaults.items():
        setattr(offer, field, value)
    if _ensure_public_slug(offer):
        update_fields.append('slug')

    offer.save(update_fields=update_fields)
    _classify(offer)
    return offer, created


def _classify(offer: Offer) -> None:
    try:
        from apps.curation.services.classifier import apply_classification

        apply_classification(offer)
    except Exception as exc:
        log.warning('classifier failed for offer_id=%s: %s', offer.id, exc)


def _ensure_public_slug(offer: Offer) -> bool:
    if offer.slug:
        return False

    offer.slug = _build_unique_slug(offer)
    offer.save(update_fields=['slug', 'updated_at'])
    return True


def _build_unique_slug(offer: Offer) -> str:
    base = slugify(offer.normalized_title or offer.title or 'oferta')
    base = (base[:MAX_SLUG_BASE_LENGTH] or 'oferta').strip('-')
    suffix = f'-{offer.id}'
    candidate = f'{base[:MAX_SLUG_LENGTH - len(suffix)]}{suffix}'

    if not _slug_exists(candidate, offer):
        return candidate

    counter = 2
    while True:
        suffix = f'-{offer.id}-{counter}'
        candidate = f'{base[:MAX_SLUG_LENGTH - len(suffix)]}{suffix}'
        if not _slug_exists(candidate, offer):
            return candidate
        counter += 1


def _slug_exists(slug: str, offer: Offer) -> bool:
    return Offer.objects.filter(slug=slug).exclude(id=offer.id).exists()
