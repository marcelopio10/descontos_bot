import logging
from dataclasses import replace
from datetime import datetime

from django.utils import timezone
from django.utils.text import slugify

from apps.offers.models import Offer, PriceHistoryEntry
from apps.offers.services.normalizer import NormalizedOffer


log = logging.getLogger(__name__)

MAX_SLUG_LENGTH = 220
MAX_SLUG_BASE_LENGTH = 200


def save_normalized_offer(
    normalized_offer: NormalizedOffer,
    *,
    observed_at: datetime | None = None,
) -> tuple[Offer, bool]:
    now = observed_at or timezone.now()
    defaults = {
        'offer_hash': normalized_offer.offer_hash,
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
        'seller_id': normalized_offer.seller_id,
        'seller_name': normalized_offer.seller_name,
        'currency_code': normalized_offer.currency_code,
        'listing_status': normalized_offer.listing_status,
        'item_condition': normalized_offer.condition,
        'available_quantity': normalized_offer.available_quantity,
        'collection_source': normalized_offer.collection_source,
        'last_seen_at': now,
        'category_source': '',
    }
    offer = Offer.objects.filter(offer_hash=normalized_offer.offer_hash).first()
    if offer is None and normalized_offer.marketplace.code == 'mercadolivre':
        offer = (
            Offer.objects
            .filter(
                marketplace=normalized_offer.marketplace,
                external_id=normalized_offer.external_id,
            )
            .order_by('id')
            .first()
        )

    if offer is None:
        offer, created = Offer.objects.get_or_create(
            offer_hash=normalized_offer.offer_hash,
            defaults={
                **defaults,
                'first_seen_at': now,
            },
        )
    else:
        created = False
    if created:
        _ensure_public_slug(offer)
        _classify(offer)
        _record_price_history(offer, collected_at=defaults['price_collected_at'])
        return offer, created

    update_fields = [*defaults.keys(), 'updated_at']
    for field, value in defaults.items():
        setattr(offer, field, value)
    if _ensure_public_slug(offer):
        update_fields.append('slug')

    offer.save(update_fields=update_fields)
    _classify(offer)
    _record_price_history(offer, collected_at=defaults['price_collected_at'])
    return offer, created


def _record_price_history(offer: Offer, *, collected_at) -> None:
    """Grava um ponto da série de preço interna (RESTR-05: uso só interno).

    Só cria uma entrada nova se o preço mudou desde a última coleta registrada,
    ou se ainda não existe nenhum histórico para a oferta. Isso evita explodir
    a tabela com uma linha idêntica a cada ciclo de scraping em que o preço
    simplesmente não mudou (o scraping roda com frequência bem maior do que a
    frequência real de variação de preço na maioria das ofertas).
    """
    last_entry = offer.price_history.order_by('-collected_at').first()
    if last_entry is not None and last_entry.price == offer.current_price:
        return
    PriceHistoryEntry.objects.create(
        offer=offer,
        price=offer.current_price,
        collected_at=collected_at,
    )


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


class OfferRepository:
    """Persistência em duas fases do fluxo API do Mercado Livre."""

    def _find_existing(self, normalized_offer: NormalizedOffer) -> Offer | None:
        offer = Offer.objects.filter(offer_hash=normalized_offer.offer_hash).first()
        if offer is not None:
            return offer
        if normalized_offer.marketplace.code == 'mercadolivre' and normalized_offer.external_id:
            return (
                Offer.objects
                .filter(
                    marketplace=normalized_offer.marketplace,
                    external_id=normalized_offer.external_id,
                )
                .order_by('id')
                .first()
            )
        return None

    def save_original(
        self,
        normalized_offer: NormalizedOffer,
        *,
        run,
        sequence: int,
        observed_at: datetime,
        source: str = '',
    ) -> tuple[Offer, object, bool]:
        from django.db import transaction
        from apps.scraping.models import ScrapingItemResult

        existing = self._find_existing(normalized_offer)
        if existing is not None and existing.affiliate_url:
            normalized_offer = replace(
                normalized_offer,
                affiliate_url=existing.affiliate_url,
            )

        with transaction.atomic():
            offer, created = save_normalized_offer(
                normalized_offer,
                observed_at=observed_at,
            )
            item_result, _ = ScrapingItemResult.objects.update_or_create(
                run=run,
                sequence=sequence,
                defaults={
                    'external_id': normalized_offer.external_id,
                    'original_url': normalized_offer.product_url,
                    'source': source or normalized_offer.collection_source,
                    'status': ScrapingItemResult.Status.PENDING,
                    'reason_code': '',
                    'error_message': '',
                    'offer': offer,
                    'processed_at': observed_at,
                },
            )
        return offer, item_result, created

    def attach_affiliate(
        self,
        offer: Offer,
        *,
        affiliate_url: str,
        generated: bool,
        run_item,
        observed_at: datetime,
        error_code: str = '',
        error_message: str = '',
    ) -> Offer:
        from django.db import transaction
        from apps.scraping.models import ScrapingItemResult

        usable_generated = bool(
            generated
            and affiliate_url
            and affiliate_url != offer.product_url
        )
        with transaction.atomic():
            if usable_generated:
                Offer.objects.filter(pk=offer.pk).update(
                    affiliate_url=affiliate_url,
                    updated_at=observed_at,
                )
                offer.affiliate_url = affiliate_url
            run_item.status = (
                ScrapingItemResult.Status.ACCEPTED
                if usable_generated
                else ScrapingItemResult.Status.AFFILIATE_FAILED
            )
            run_item.reason_code = (
                ''
                if usable_generated
                else (error_code or 'affiliate_generation_failed')
            )
            run_item.error_message = '' if usable_generated else error_message[:2000]
            run_item.processed_at = observed_at
            run_item.save(update_fields=[
                'status',
                'reason_code',
                'error_message',
                'processed_at',
                'updated_at',
            ])
        return offer
