import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.curation.services.blacklist import filter_blacklisted_offers
from apps.offers.models import Offer
from apps.offers.services.freshness import get_freshness_cutoff
from apps.offers.services.site_publisher import DISCLOSURE
from apps.social_posts.services.link_builder import build_instagram_tracked_url

log = logging.getLogger(__name__)

# Pool amplo o bastante para o score decidir a vitrine, e não a ordem do banco.
POOL_MULTIPLIER = 12
POOL_FLOOR = 60
# Com 5 vagas e 3 marketplaces, o teto de 2 garante ao menos dois marketplaces
# representados sem exigir simetria artificial.
MAX_PER_MARKETPLACE = 2


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
    """Seleciona a vitrine do link da bio com as regras editoriais do canal.

    Item 12 da Onda 2. Até 2026-08-23 esta função ordenava por `-discount_pct` e
    cortava — o que fazia da vitrine de aquisição uma sobra de catálogo: a
    publicada no dia trazia "O Idiota" a R$ 1,99 (97% de desconto), uma caneta de
    bordado russa e um kit de retoque de cabelo. Quem chega pelo Instagram vê
    isso antes de ver o canal.

    Ordenar por desconto premia exatamente o desconto falso que o `quality_score`
    existe para punir. Agora a vitrine passa pelo mesmo funil do canal: blacklist,
    janela de recência, score mínimo de qualidade, e diversidade de família e de
    marketplace.

    O pool vem por `-last_seen_at`, não por desconto: ordenar o pool pelo mesmo
    critério que se quer corrigir enviesaria a amostra antes de o score entrar.
    """
    # Imports locais: `selector` puxa distribution/curation, e este módulo é
    # carregado pelo site_publisher dentro do caminho de publicação.
    from apps.curation.services.product_family import offer_family_key
    from apps.curation.services.quality_score import quality_score_breakdown
    from apps.curation.services.selector import get_selection_config

    cutoff = get_freshness_cutoff()
    pool_size = max(POOL_FLOOR, limit * POOL_MULTIPLIER)
    pool = filter_blacklisted_offers(list(
        Offer.objects
        .select_related('marketplace', 'category')
        .filter(is_active=True, slug__isnull=False)
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
        .filter(discount_pct__gt=0)
        .filter(last_seen_at__gte=cutoff)
        .order_by('-last_seen_at', 'id')[:pool_size],
    ))

    config = get_selection_config()
    scored: list[tuple[float, Offer]] = []
    for offer in pool:
        breakdown = quality_score_breakdown(offer)
        if breakdown.score < config.min_quality_score:
            continue
        scored.append((breakdown.score, offer))

    scored.sort(
        key=lambda item: (
            item[0],
            float(item[1].discount_pct or 0),
            -float(item[1].current_price or 0),
        ),
        reverse=True,
    )

    aprovadas = [offer for _, offer in scored]

    # Relaxa em estágios, cedendo primeiro no que menos aparece para quem olha a
    # vitrine. Concentração de marketplace é invisível ao visitante; três tênis
    # seguidos não são — foi o que a primeira versão desta seleção produziu.
    selected = _pick_diverse(aprovadas, limit, offer_family_key, max_por_marketplace=MAX_PER_MARKETPLACE)
    estagio = 'estrito'

    if len(selected) < limit:
        selected = _pick_diverse(aprovadas, limit, offer_family_key, max_por_marketplace=None)
        estagio = 'sem_teto_de_marketplace'

    if len(selected) < limit:
        # Último recurso: vitrine curta comunica menos que vitrine repetida.
        ja_escolhidas = {offer.id for offer in selected}
        for offer in aprovadas:
            if len(selected) == limit:
                break
            if offer.id in ja_escolhidas:
                continue
            selected.append(offer)
        estagio = 'so_por_score'

    if not selected:
        raise ValueError(
            'Nenhuma oferta aprovada no score de qualidade dentro da janela de '
            f'recência (pool={len(pool)}, score mínimo={config.min_quality_score}).'
        )

    log.info(
        'bio_links.selecionadas itens=%s pool=%s aprovadas=%s estagio=%s',
        len(selected), len(pool), len(scored), estagio,
    )
    return selected


def _pick_diverse(
    offers: list[Offer],
    limit: int,
    family_key,
    *,
    max_por_marketplace: int | None,
) -> list[Offer]:
    """Uma oferta por família; teto por marketplace só quando informado."""
    selected: list[Offer] = []
    familias_usadas: set[str] = set()
    por_marketplace: dict[int, int] = defaultdict(int)

    for offer in offers:
        if len(selected) == limit:
            break
        familia = family_key(offer)
        if familia and familia in familias_usadas:
            continue
        if (
            max_por_marketplace is not None
            and por_marketplace[offer.marketplace_id] >= max_por_marketplace
        ):
            continue
        selected.append(offer)
        if familia:
            familias_usadas.add(familia)
        por_marketplace[offer.marketplace_id] += 1

    return selected


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
