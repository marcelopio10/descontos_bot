import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.offers.models import Offer
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.caption_builder import build_caption
from apps.social_posts.services.image_renderer import (
    render_carousel_assets,
    render_feed_asset,
    render_story_asset,
)
from apps.social_posts.services.link_builder import build_instagram_tracked_url

logger = logging.getLogger(__name__)

FRESHNESS_HOURS = 36


def generate_feed_post(top: int = 1) -> InstagramPost:
    offer = _get_offer_by_rank(top)
    asset = render_feed_asset(offer)
    return _create_post(
        post_format=InstagramPost.Format.FEED,
        primary_offer=offer,
        related_offers=[],
        asset_paths=[asset.path],
        medium='bio',
    )


def generate_story(top: int = 1) -> InstagramPost:
    offer = _get_offer_by_rank(top)
    return generate_story_for_offer(offer)


def generate_story_for_offer(offer: Offer) -> InstagramPost:
    existing = (
        InstagramPost.objects
        .filter(format=InstagramPost.Format.STORY, primary_offer=offer)
        .order_by('-created_at')
        .first()
    )
    if existing:
        return existing

    asset = render_story_asset(offer)
    return _create_post(
        post_format=InstagramPost.Format.STORY,
        primary_offer=offer,
        related_offers=[],
        asset_paths=[asset.path],
        medium='story',
    )


def generate_carousel(count: int = 5) -> InstagramPost:
    offers = _get_ranked_offers(count)
    assets = render_carousel_assets(offers)
    return _create_post(
        post_format=InstagramPost.Format.CAROUSEL,
        primary_offer=offers[0],
        related_offers=offers[1:],
        asset_paths=[asset.path for asset in assets],
        medium='carousel_link',
    )


def _create_post(
    post_format: str,
    primary_offer: Offer,
    related_offers: list[Offer],
    asset_paths: list[str],
    medium: str,
) -> InstagramPost:
    group_cta = _next_group_cta()
    with transaction.atomic():
        post = InstagramPost.objects.create(
            format=post_format,
            status=InstagramPost.Status.READY,
            primary_offer=primary_offer,
            asset_paths=asset_paths,
            caption=build_caption(primary_offer, group_cta=group_cta),
            sticker_target_url=build_instagram_tracked_url(primary_offer, medium),
        )
        if related_offers:
            post.related_offers.set(related_offers)

    if post_format == InstagramPost.Format.STORY:
        _trigger_handoff(post)
    return post


def _trigger_handoff(post: InstagramPost) -> None:
    # Import local pra evitar ciclo de import com modelos no boot.
    from apps.social_posts.services.instagram_handoff_telegram import (
        HandoffDisabled,
        HandoffError,
        deliver_post_to_handoff,
    )

    try:
        result = deliver_post_to_handoff(post)
    except HandoffDisabled as exc:
        logger.info('handoff.disabled post_id=%s reason=%s', post.id, exc)
        return
    except HandoffError as exc:
        logger.warning('handoff.failed post_id=%s error=%s', post.id, exc)
        post.published_error = f'handoff: {exc}'[:4000]
        post.save(update_fields=['published_error', 'updated_at'])
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception('handoff.unexpected_error post_id=%s', post.id)
        post.published_error = f'handoff inesperado: {exc}'[:4000]
        post.save(update_fields=['published_error', 'updated_at'])
        return

    logger.info(
        'handoff.delivered post_id=%s text_msg=%s doc_msg=%s skipped=%s',
        post.id, result.text_message_id, result.document_message_id, result.skipped,
    )


def _get_ranked_offers(limit: int) -> list[Offer]:
    generated_offer_ids = _get_generated_offer_ids()
    cutoff = timezone.now() - timedelta(hours=FRESHNESS_HOURS)
    offers = list(
        Offer.objects
        .select_related('marketplace')
        .filter(is_active=True, slug__isnull=False)
        .filter(marketplace__code='amazon')
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
        .exclude(id__in=generated_offer_ids)
        .filter(created_at__gte=cutoff)
        .order_by('-discount_pct', 'current_price', 'title')[:limit],
    )
    if len(offers) < limit:
        raise ValueError(f'Ofertas publicáveis insuficientes: {len(offers)} de {limit}.')
    return offers


def _get_offer_by_rank(rank: int) -> Offer:
    if rank < 1:
        raise ValueError('O ranking da oferta deve ser maior ou igual a 1.')
    return _get_ranked_offers(rank)[rank - 1]


def _next_group_cta() -> str:
    # Alterna WhatsApp/Telegram por paridade do total de posts gerados.
    return 'telegram' if InstagramPost.objects.count() % 2 == 1 else 'whatsapp'


def _get_generated_offer_ids() -> set[int]:
    primary_offer_ids = InstagramPost.objects.values_list(
        'primary_offer_id',
        flat=True,
    )
    related_offer_ids = InstagramPost.related_offers.through.objects.values_list(
        'offer_id',
        flat=True,
    )
    return set(primary_offer_ids) | set(related_offer_ids)
