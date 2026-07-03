from __future__ import annotations

from typing import Any

from apps.curation.models import CurationRun
from apps.curation.services.ai_schema import INPUT_SCHEMA_VERSION
from apps.curation.services.baseline_snapshot import serialize_offer_for_ai, summarize_quality
from apps.curation.services.batch_optimizer import DEFAULT_TARGET_DISTRIBUTION
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer

EDITORIAL_POLICY = {
    'preferred_categories': [
        'beleza_cuidados',
        'moda_feminina',
        'moda_masculina',
        'tecnologia_cotidiana',
        'casa_cozinha',
    ],
    'blocked_themes': [
        'adulto',
        'sexual',
        'obsceno',
        'armas',
        'arma_de_brinquedo',
        'ferramenta_pesada',
        'industrial',
        'walkie_talkie',
        'radio_comunicador',
        'camera_seguranca',
    ],
    'tone': 'honesto, direto, persuasivo sem exagero',
}

BASELINE_RULES = {
    'min_discount_percentage': 20,
    'min_quality_score': 55,
    'priority_quality_score': 70,
}


def build_ai_curation_payload(
    *,
    run: CurationRun,
    channel: SocialChannel,
    offers: list[Offer],
    batch_size: int,
    observer_context: dict[str, Any] | None = None,
    target_distribution: dict[str, float] | None = None,
) -> dict[str, Any]:
    serialized_offers = [serialize_offer_for_ai(offer) for offer in offers]
    target = target_distribution or DEFAULT_TARGET_DISTRIBUTION
    return {
        'schema_version': INPUT_SCHEMA_VERSION,
        'run': {
            'run_id': run.id,
            'mode': run.mode,
            'channel_code': channel.code,
            'batch_size': batch_size,
            'target_distribution': target,
        },
        'editorial_policy': EDITORIAL_POLICY,
        'baseline_rules': BASELINE_RULES,
        'observer_context': observer_context or {},
        'baseline_summary': {
            'candidate_count': len(serialized_offers),
            'marketplace_counts': _count_by(serialized_offers, 'marketplace_code'),
            'quality_score_breakdown': summarize_quality(serialized_offers),
        },
        'offers': serialized_offers,
    }


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or 'desconhecido')
        counts[value] = counts.get(value, 0) + 1
    return counts
