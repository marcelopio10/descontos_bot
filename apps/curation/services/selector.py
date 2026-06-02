from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.curation.services.blacklist import (
    apply_blacklist_exclusion,
    get_blacklist_terms,
    is_blacklisted,
)
from apps.curation.services.quality_score import quality_score
from apps.curation.services.settings import get_decimal_setting, get_integer_setting
from apps.distribution.models import Delivery, SocialChannel
from apps.offers.models import Offer
from apps.offers.services.freshness import get_freshness_cutoff


DEFAULT_GLOBAL_LIMIT = 20
DEFAULT_MARKETPLACE_LIMIT = 10
DEFAULT_MIN_DISCOUNT = Decimal('20')
DEFAULT_MIN_QUALITY_SCORE = 0.0
CANDIDATE_POOL_MULTIPLIER = 5
CANDIDATE_POOL_FLOOR = 60


@dataclass(frozen=True)
class SelectionConfig:
    global_limit: int
    marketplace_limit: int
    min_discount_percentage: Decimal
    min_quality_score: float


def get_selection_config() -> SelectionConfig:
    return SelectionConfig(
        global_limit=max(
            1,
            get_integer_setting('offer_limit_global', DEFAULT_GLOBAL_LIMIT),
        ),
        marketplace_limit=max(
            1,
            get_integer_setting('offer_limit_per_marketplace', DEFAULT_MARKETPLACE_LIMIT),
        ),
        min_discount_percentage=get_decimal_setting(
            'min_discount_percentage',
            DEFAULT_MIN_DISCOUNT,
        ),
        min_quality_score=float(
            get_decimal_setting(
                'min_quality_score',
                Decimal(str(DEFAULT_MIN_QUALITY_SCORE)),
            )
        ),
    )


def select_offers_for_channel(
    channel: SocialChannel,
    config: SelectionConfig | None = None,
) -> list[Offer]:
    config = config or get_selection_config()
    queryset = _eligible_offers(channel, config)

    pool_size = max(CANDIDATE_POOL_FLOOR, config.global_limit * CANDIDATE_POOL_MULTIPLIER)
    candidates = list(queryset[:pool_size])

    blacklist_terms = get_blacklist_terms()
    candidates = [
        offer for offer in candidates
        if not is_blacklisted(offer, terms=blacklist_terms)
    ]

    scored = [(offer, quality_score(offer)) for offer in candidates]
    scored = [
        (offer, score)
        for offer, score in scored
        if score >= config.min_quality_score
    ]
    scored.sort(
        key=lambda item: (item[1], item[0].discount_pct or 0, item[0].current_price or 0),
        reverse=True,
    )

    selected: list[Offer] = []
    per_marketplace_count: dict[int, int] = {}

    for offer, _ in scored:
        marketplace_count = per_marketplace_count.get(offer.marketplace_id, 0)
        if marketplace_count >= config.marketplace_limit:
            continue

        selected.append(offer)
        per_marketplace_count[offer.marketplace_id] = marketplace_count + 1

        if len(selected) >= config.global_limit:
            break

    return selected


def _eligible_offers(channel: SocialChannel, config: SelectionConfig) -> QuerySet[Offer]:
    sent_delivery_filter = Q(
        deliveries__social_channel=channel,
        deliveries__delivery_status=Delivery.DeliveryStatus.SENT,
    )

    queryset = (
        Offer.objects.select_related('marketplace')
        .filter(
            is_active=True,
            marketplace__is_active=True,
            title__gt='',
            product_url__gt='',
            current_price__gt=0,
            discount_pct__gte=config.min_discount_percentage,
            last_seen_at__gte=get_freshness_cutoff(),
        )
        .exclude(sent_delivery_filter)
        .order_by('-discount_pct', '-current_price', 'title')
    )

    queryset = apply_blacklist_exclusion(queryset)

    if channel.link_strategy == SocialChannel.LinkStrategy.BRIDGE_ONLY:
        queryset = queryset.filter(slug__isnull=False).exclude(slug='')

    return queryset
