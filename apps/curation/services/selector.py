import logging
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem
from apps.curation.services.blacklist import (
    apply_blacklist_exclusion,
    get_blacklist_terms,
    is_blacklisted,
)
from apps.curation.services.quality_score import quality_score_breakdown
from apps.curation.services.product_family import offer_family_key
from apps.curation.services.recurrence import (
    filter_blocked_recurrence,
    filter_saturated_families,
    recurrence_score_multiplier,
    recurrence_signal,
)
from apps.curation.services.settings import get_decimal_setting, get_integer_setting
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.delivery import _should_republish_after_improvement
from apps.offers.models import Category, Offer
from apps.offers.services.freshness import get_freshness_cutoff


log = logging.getLogger('apps.curation.selector')


DEFAULT_GLOBAL_LIMIT = 20
DEFAULT_MARKETPLACE_LIMIT = 10
DEFAULT_MIN_DISCOUNT = Decimal('20')
DEFAULT_MIN_QUALITY_SCORE = Decimal('55')  # threshold soft (Sprint 2)
DEFAULT_PRIORITY_QUALITY_SCORE = Decimal('70')
CANDIDATE_POOL_MULTIPLIER = 5
CANDIDATE_POOL_FLOOR = 60
EXPOSURE_QUOTA_FLAG = 'exposure_quota_enabled'
SIMILAR_TITLE_PREFIX = 50
# Mesmo teto que `batch_optimizer` aplica no fluxo de curadoria IA.
MAX_PER_FAMILY = 1
SIMILAR_TITLE_MIN_TOKENS = 4
SIMILAR_TITLE_JACCARD_THRESHOLD = 0.75
TITLE_STOPWORDS = frozenset({
    'com',
    'para',
    'por',
    'sem',
    'masculino',
    'masculina',
    'feminino',
    'feminina',
})


@dataclass(frozen=True)
class SelectionConfig:
    global_limit: int
    marketplace_limit: int
    min_discount_percentage: Decimal
    min_quality_score: float
    priority_quality_score: float
    exposure_quota_enabled: bool


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
                DEFAULT_MIN_QUALITY_SCORE,
            )
        ),
        priority_quality_score=float(
            get_decimal_setting(
                'priority_quality_score',
                DEFAULT_PRIORITY_QUALITY_SCORE,
            )
        ),
        exposure_quota_enabled=bool(
            get_integer_setting(EXPOSURE_QUOTA_FLAG, 0)
        ),
    )


def select_offers_for_channel(
    channel: SocialChannel,
    config: SelectionConfig | None = None,
    *,
    observer_context: dict | None = None,
) -> list[Offer]:
    """Seleção determinística legada (usada por `run_bot.py` no canal WhatsApp
    legado e por `publish_telegram.py`). Aceita `observer_context` opcional
    (Sprint 6 / Tarefa 6.2, achado P3) só para dar paridade com o fluxo de
    curadoria IA — hoje nenhum caller de produção passa esse argumento; a
    correção obrigatória do achado P3 (contexto real em vez de dict estático)
    é escopo de `prepare_ai_curation_batch.py`, que é o único ponto citado no
    plano como responsável pela curadoria IA de WhatsApp em produção. Ligar
    isto também no seletor legado/Telegram é uma decisão futura do dono, não
    coberta por esta tarefa.
    """
    config = config or get_selection_config()
    queryset = _eligible_offers(channel, config)

    pool_size = max(CANDIDATE_POOL_FLOOR, config.global_limit * CANDIDATE_POOL_MULTIPLIER)
    # `filter_saturated_families` faltava aqui (achado 2026-08-21). Os gates de
    # diversidade escritos junto com `product_family.py` cobriam só o fluxo de
    # curadoria IA, e este selector é o **fallback** de quando a IA falha — ou
    # seja, justamente o caminho que roda quando algo dá errado. Medido no dia:
    # dos 25 envios após o restart, 17 saíram por aqui, entre eles 7 fones de
    # ouvido em 3 minutos.
    raw_candidates = filter_saturated_families(
        filter_blocked_recurrence(list(queryset[:pool_size]), channel),
        channel,
    )

    blacklist_terms = get_blacklist_terms()
    candidates: list[Offer] = []
    for offer in raw_candidates:
        if is_blacklisted(offer, terms=blacklist_terms):
            log.info(
                'selector_drop offer_id=%s reason=blacklist category=%s title=%r',
                offer.id,
                offer.category.code if offer.category_id else '-',
                (offer.title or '')[:120],
            )
            continue
        candidates.append(offer)

    evaluated = []
    for offer in candidates:
        breakdown = quality_score_breakdown(offer, observer_context=observer_context)
        signal = recurrence_signal(offer, channel)
        recurrence_multiplier = recurrence_score_multiplier(signal)
        if recurrence_multiplier != 1.0:
            from dataclasses import replace
            breakdown = replace(
                breakdown,
                score=breakdown.score * recurrence_multiplier,
                multipliers={**breakdown.multipliers, 'recurrence': recurrence_multiplier},
                notes=[*breakdown.notes, 'família recorrente; prioridade reduzida'],
            )
        if breakdown.score < config.min_quality_score:
            log.info(
                'selector_drop offer_id=%s reason=low_score score=%.2f classification=%s '
                'category=%s notes=%s',
                offer.id, breakdown.score, breakdown.classification,
                offer.category.code if offer.category_id else '-',
                breakdown.notes,
            )
            continue
        evaluated.append((offer, breakdown))

    # Prioritários primeiro, depois fila secundária. Empata por desconto + preço (estável).
    evaluated.sort(
        key=lambda item: (
            1 if item[1].score >= config.priority_quality_score else 0,
            item[1].score,
            float(item[0].discount_pct or 0),
            float(item[0].current_price or 0),
        ),
        reverse=True,
    )

    quotas = _resolve_category_quotas(config) if config.exposure_quota_enabled else {}

    selected: list[Offer] = []
    per_marketplace_count: dict[int, int] = defaultdict(int)
    per_category_count: dict[str, int] = defaultdict(int)
    per_family_count: dict[str, int] = defaultdict(int)
    seen_prefixes: set[str] = set()
    selected_token_sets: list[tuple[int, set[str]]] = []

    def _category_of(offer: Offer) -> str:
        return offer.category.code if offer.category_id else 'sem_categoria'

    def _try_pick(offer: Offer, breakdown, *, respect_quota: bool, pass_label: str) -> bool:
        if offer in selected:
            return False

        prefix = (offer.normalized_title or '')[:SIMILAR_TITLE_PREFIX].strip()
        if prefix and prefix in seen_prefixes:
            log.info(
                'selector_drop offer_id=%s reason=similar_title prefix=%r',
                offer.id, prefix,
            )
            return False

        tokens = _title_tokens(offer)
        similar_offer_id = _find_similar_selected_offer(tokens, selected_token_sets)
        if similar_offer_id is not None:
            log.info(
                'selector_drop offer_id=%s reason=similar_title_tokens similar_offer_id=%s tokens=%s',
                offer.id,
                similar_offer_id,
                sorted(tokens),
            )
            return False

        # Teto de família DENTRO da seleção. O filtro de histórico acima não
        # cobre isto: os envios deste mesmo ciclo ainda não existem no banco
        # quando a seleção é montada, então sem este teto os 7 fones de ouvido
        # saem juntos mesmo com o espaçamento ligado. É o equivalente ao
        # `max_per_family=1` que `batch_optimizer` aplica no fluxo de curadoria.
        familia = offer_family_key(offer)
        if familia and per_family_count[familia] >= MAX_PER_FAMILY:
            log.info(
                'selector_drop offer_id=%s reason=family_limit family=%s title=%r',
                offer.id, familia, (offer.title or '')[:80],
            )
            return False

        if per_marketplace_count[offer.marketplace_id] >= config.marketplace_limit:
            log.info(
                'selector_drop offer_id=%s reason=marketplace_limit marketplace=%s limit=%s',
                offer.id,
                offer.marketplace.code if offer.marketplace_id else '-',
                config.marketplace_limit,
            )
            return False

        category_code = _category_of(offer)
        if respect_quota:
            quota = quotas.get(category_code)
            if quota is not None and per_category_count[category_code] >= quota:
                # Cota cheia — segura na 1ª passada; pode ser revista na 2ª.
                return False
            if quota is None:
                # Categoria sem quota só entra na 2ª passada.
                return False

        selected.append(offer)
        per_marketplace_count[offer.marketplace_id] += 1
        per_category_count[category_code] += 1
        if familia:
            per_family_count[familia] += 1
        if prefix:
            seen_prefixes.add(prefix)
        if len(tokens) >= SIMILAR_TITLE_MIN_TOKENS:
            selected_token_sets.append((offer.id, tokens))

        log.info(
            'selector_pick offer_id=%s score=%.2f classification=%s decision=%s '
            'category=%s marketplace=%s discount=%s pass=%s',
            offer.id, breakdown.score, breakdown.classification, breakdown.decision,
            category_code,
            offer.marketplace.code if offer.marketplace_id else '-',
            offer.discount_pct, pass_label,
        )
        return True

    if config.exposure_quota_enabled:
        # 1ª passada: respeitar cotas das categorias quentes.
        for offer, breakdown in evaluated:
            if len(selected) >= config.global_limit:
                break
            _try_pick(offer, breakdown, respect_quota=True, pass_label='quota')

        # 2ª passada: preencher slots restantes sem respeitar quota
        # (categorias sem quota e overflow das quentes podem entrar).
        for offer, breakdown in evaluated:
            if len(selected) >= config.global_limit:
                break
            _try_pick(offer, breakdown, respect_quota=False, pass_label='overflow')
    else:
        for offer, breakdown in evaluated:
            if len(selected) >= config.global_limit:
                break
            _try_pick(offer, breakdown, respect_quota=False, pass_label='flat')

    if config.exposure_quota_enabled:
        log.info(
            'selector_summary picked=%d quotas=%s actual=%s',
            len(selected), quotas, dict(per_category_count),
        )

    return selected


def _title_tokens(offer: Offer) -> set[str]:
    text = _strip_accents(offer.normalized_title or offer.title or '').lower()
    return {
        token
        for token in re.findall(r'[a-z0-9]+', text)
        if len(token) >= 3 and token not in TITLE_STOPWORDS
    }


def _find_similar_selected_offer(
    tokens: set[str],
    selected_token_sets: list[tuple[int, set[str]]],
) -> int | None:
    if len(tokens) < SIMILAR_TITLE_MIN_TOKENS:
        return None
    for offer_id, selected_tokens in selected_token_sets:
        union = tokens | selected_tokens
        if not union:
            continue
        similarity = len(tokens & selected_tokens) / len(union)
        if similarity >= SIMILAR_TITLE_JACCARD_THRESHOLD:
            return offer_id
    return None


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _resolve_category_quotas(config: SelectionConfig) -> dict[str, int]:
    """Converte exposure_quota_pct (%) das categorias ativas em slots absolutos
    com base em config.global_limit. Categorias sem quota não entram no mapa.
    """
    quotas: dict[str, int] = {}
    for category in Category.objects.filter(
        is_active=True,
        exposure_quota_pct__isnull=False,
    ):
        pct = float(category.exposure_quota_pct or 0)
        if pct <= 0:
            continue
        slots = max(1, math.ceil(config.global_limit * pct / 100.0))
        quotas[category.code] = slots
    return quotas


def _eligible_offers(channel: SocialChannel, config: SelectionConfig) -> QuerySet[Offer]:
    sent_deliveries = Delivery.objects.select_related('offer').filter(
        social_channel=channel,
        delivery_status=Delivery.DeliveryStatus.SENT,
    )
    blocked_sent_offer_ids = [
        delivery.offer_id
        for delivery in sent_deliveries
        if not _should_republish_after_improvement(delivery, delivery.offer, '')
    ]

    # Achado 2026-07-22: sem isso, uma oferta com envio pendente num lote ainda
    # ativo (curado mas não consumido) continuava elegível — cada novo ciclo de
    # preparo reordenava o pool por desconto e pegava de novo o mesmo topo do
    # ranking, gerando lotes com 80-90% de duplicatas (skipped) quando o
    # consumo atrasa. Só existe efeito prático desde que a fila desacoplada
    # (`usa_fila_desacoplada`) virou padrão: no fluxo síncrono antigo (seleciona
    # e envia no mesmo ciclo) não havia essa janela de "pendente entre ciclos".
    pending_offer_ids = CuratedBatchItem.objects.filter(
        batch__channel=channel,
        batch__status=CuratedBatch.Status.READY,
        batch__expires_at__gt=timezone.now(),
        send_status=CuratedBatchItem.SendStatus.PENDING,
    ).values('offer_id')

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
        .exclude(id__in=blocked_sent_offer_ids)
        .exclude(id__in=pending_offer_ids)
        .order_by('-discount_pct', '-current_price', 'title')
    )

    queryset = apply_blacklist_exclusion(queryset)

    if channel.link_strategy == SocialChannel.LinkStrategy.BRIDGE_ONLY:
        queryset = queryset.filter(slug__isnull=False).exclude(slug='')

    return queryset
