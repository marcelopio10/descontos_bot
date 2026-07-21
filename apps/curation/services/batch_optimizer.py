from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import floor
from typing import Any, Iterable

from apps.curation.services.ai_schema import SAFETY_RISK_FLAGS

# Sprint 6 / Tarefa 6.4 (item 20 do backlog, achado do laudo diagnóstico
# externo 4.5): reponderação por receita real, tratada como EXPERIMENTO
# controlado — não é decisão permanente. Distribuição anterior (Sprints 3-5):
# ml=0.40 / amazon=0.30 / shopee=0.30.
#
# Base factual (laudo externo, doc fora deste repositório — os dados deste
# banco hoje são insuficientes para rederivar os percentuais: só ~1 mês de
# comissão ML e ZERO registros Amazon/Shopee, ver baseline abaixo):
#   - Mercado Livre = 92% da comissão real reportada.
#   - Amazon converte melhor por clique (20,7%) mas com volume de cliques
#     baixo — a distribuição anterior (30% dos slots) sub-representava o
#     que paga (ML) e não validava o potencial de Amazon com mais exposição.
#   - Shopee: Affiliate API ainda travada por padrão em produção
#     (SHOPEE_AFFILIATE_ENABLED=false) — sem nenhuma comissão real
#     mensurada até hoje, mesmo recebendo ~30% dos slots.
#
# Baseline ANTES desta mudança (registrado em 2026-07-21, para comparação
# futura — apps.analytics.services.operational_metrics.
# deliveries_vs_commission_by_marketplace_week(weeks=12), já usando o fix de
# apps/analytics/services/operational_metrics.py que passou a agrupar por
# period_end em vez de period_start, commit 9627599):
#   - Only mercadolivre teve comissão registrada em toda a janela de 12
#     semanas: R$ 234,73 / 14 conversões, na semana de 2026-06-01, contra
#     ~1018 envios ML naquela mesma semana.
#   - amazon: R$ 0,00 de comissão em todas as 12 semanas, apesar de volumes
#     de envio de dezenas a centenas por semana (ex.: 695 envios na semana
#     de 2026-05-18).
#   - shopee: R$ 0,00 de comissão nas semanas em que já havia envio
#     (a partir de meados de junho/2026; 10 a 120 envios/semana).
#
# Nova distribuição-alvo: aumenta ML (a fonte de receita real hoje),
# aumenta levemente Amazon (aposta controlada — converte bem por clique,
# vale testar mais exposição para ver se a comissão acompanha) e reduz
# Shopee (sem receita real mensurada e com o afiliado ainda desligado em
# produção). Não é um corte a zero — mantém Shopee como fatia pequena para
# não perder cobertura/aprendizado desse marketplace.
DEFAULT_TARGET_DISTRIBUTION: dict[str, float] = {
    'mercadolivre': 0.55,
    'amazon': 0.35,
    'shopee': 0.10,
}

MARKETPLACE_ALIASES = {
    'mercado_livre': 'mercadolivre',
    'mercado livre': 'mercadolivre',
    'ml': 'mercadolivre',
}

BLOCKED_EDITORIAL_TERMS: tuple[str, ...] = (
    'adulto',
    'sexual',
    'obsceno',
    'arma',
    'armas',
    'arma de brinquedo',
    'ferramenta pesada',
    'industrial',
    'walkie talkie',
    'walkie-talkie',
    'radio comunicador',
    'rádio comunicador',
    'camera seguranca',
    'câmera segurança',
    'camera de seguranca',
    'câmera de segurança',
)


@dataclass(frozen=True)
class OptimizedBatch:
    selected: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    target_distribution: dict[str, float]
    actual_distribution: dict[str, int]

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def optimize_curation_batch(
    decisions: Iterable[dict[str, Any]],
    *,
    batch_size: int,
    target_distribution: dict[str, float] | None = None,
    min_ai_score: float | Decimal | None = None,
) -> OptimizedBatch:
    """Build a safe batch from AI decisions without replacing AI selection.

    The AI is the curator: only decisions explicitly marked
    selected_for_batch=true can enter the final batch. This function is a safety
    gate and persistence normalizer, not a deterministic selector. It removes
    unsafe/invalid selected items, caps the batch size, normalizes positions, and
    recomputes the final distribution from the surviving AI-selected items.
    """
    if batch_size <= 0:
        return OptimizedBatch(selected=[], rejected=list(decisions), target_distribution=_target(target_distribution), actual_distribution={})

    target = _target(target_distribution)
    normalized_decisions: list[dict[str, Any]] = []
    for original in decisions:
        decision = dict(original)
        decision['marketplace_code'] = _normalize_marketplace_code(decision.get('marketplace_code'))
        normalized_decisions.append(decision)

    eligibility = [_is_eligible(decision, min_ai_score=min_ai_score) for decision in normalized_decisions]
    ai_selected_flags = [bool(decision.get('selected_for_batch')) for decision in normalized_decisions]
    canonical_duplicate_indices = _canonical_duplicate_indices(normalized_decisions, eligibility, ai_selected_flags)

    selected_candidates: list[dict[str, Any]] = []
    approved_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, decision in enumerate(normalized_decisions):
        ai_selected = ai_selected_flags[index]
        eligible = eligibility[index] and index not in canonical_duplicate_indices
        if eligible:
            approved_candidates.append(decision)
        if ai_selected and eligible:
            selected_candidates.append(decision)
        else:
            decision['selected_for_batch'] = False
            decision['batch_position'] = None
            rejected.append(decision)

    selected = sorted(selected_candidates, key=_ai_selection_key)[:batch_size]
    if batch_size >= 3:
        # Keep the AI's safety/editorial gate, but repair a missing marketplace
        # slot when the model approved a safe candidate and selected none from
        # that marketplace. Without this floor, the target mix is only advice
        # and production batches can silently become 100% ML/Amazon.
        selected_codes = {item['marketplace_code'] for item in selected}
        available_codes = {item['marketplace_code'] for item in approved_candidates}
        for marketplace_code in target:
            if marketplace_code in selected_codes or marketplace_code not in available_codes:
                continue
            replacement = next(
                item for item in approved_candidates
                if item['marketplace_code'] == marketplace_code
            )
            selected.append(replacement)
            selected_codes.add(marketplace_code)
        selected = sorted(selected, key=_ai_selection_key)[:batch_size]
    for position, decision in enumerate(selected, start=1):
        decision['selected_for_batch'] = True
        decision['batch_position'] = position

    actual_distribution: dict[str, int] = {}
    for decision in selected:
        marketplace = decision['marketplace_code']
        actual_distribution[marketplace] = actual_distribution.get(marketplace, 0) + 1

    return OptimizedBatch(
        selected=selected,
        rejected=rejected,
        target_distribution=target,
        actual_distribution=actual_distribution,
    )


def _target(target_distribution: dict[str, float] | None) -> dict[str, float]:
    source = target_distribution or DEFAULT_TARGET_DISTRIBUTION
    normalized = {
        _normalize_marketplace_code(marketplace): float(weight)
        for marketplace, weight in source.items()
        if float(weight) > 0
    }
    total = sum(normalized.values())
    if total <= 0:
        return dict(DEFAULT_TARGET_DISTRIBUTION)
    return {marketplace: weight / total for marketplace, weight in normalized.items()}


def _quota_counts(batch_size: int, target: dict[str, float]) -> dict[str, int]:
    raw = {marketplace: batch_size * weight for marketplace, weight in target.items()}
    quotas = {marketplace: floor(value) for marketplace, value in raw.items()}
    missing = batch_size - sum(quotas.values())
    remainders = sorted(
        raw.items(),
        key=lambda item: (-(item[1] - floor(item[1])), _marketplace_priority(item[0])),
    )
    for marketplace, _ in remainders[:missing]:
        quotas[marketplace] += 1
    return quotas


def _is_eligible(decision: dict[str, Any], *, min_ai_score: float | Decimal | None) -> bool:
    if decision.get('classification') != 'approved':
        return False
    if set(decision.get('risk_flags') or []) & SAFETY_RISK_FLAGS:
        return False
    image_decision = str(decision.get('image_decision') or '').strip().lower()
    if image_decision in {'improper', 'adult_content', 'obscene', 'blocked'}:
        return False
    if _contains_blocked_editorial_theme(decision):
        return False
    if not str(decision.get('rewritten_caption_whatsapp') or '').strip():
        return False
    if not str(decision.get('rewritten_caption_telegram') or '').strip():
        return False
    if min_ai_score is not None and _score(decision) < float(min_ai_score):
        return False
    return True


def _canonical_duplicate_indices(
    decisions: list[dict[str, Any]],
    eligibility: list[bool],
    ai_selected_flags: list[bool],
) -> set[int]:
    """Indices to drop so at most one candidate survives per produto_canonico_id (achado P8).

    `produto_canonico_id` is computed at ingestion time (see
    apps.offers.services.normalizer.build_produto_canonico_id) and is expected
    to already be attached to each decision dict by the caller (e.g.
    ai_curator._enrich_decisions_with_offer_fields), since the AI output
    itself doesn't carry it. An empty/missing value never triggers dedup —
    only decisions sharing the same non-empty canonical id compete.

    Only decisions that are otherwise eligible compete for the canonical slot:
    an ineligible duplicate (e.g. safety-blocked, missing captions) never
    blocks its eligible sibling from surviving. Among competing duplicates the
    winner is chosen, in order: (1) AI-selected beats not-selected — we never
    want to discard the only viable AI-selected candidate for a product just
    because a higher-scored but unselected/ineligible duplicate exists; (2)
    higher ai_score; (3) lower current_price (cheaper is the better deal for
    the reader); (4) lower offer_id, purely for determinism. Losers are folded
    into the normal `rejected` bucket exactly like any other ineligible
    decision.
    """
    indices_by_canonico: dict[str, list[int]] = {}
    for index, decision in enumerate(decisions):
        if not eligibility[index]:
            continue
        canonico = str(decision.get('produto_canonico_id') or '').strip()
        if not canonico:
            continue
        indices_by_canonico.setdefault(canonico, []).append(index)

    duplicate_indices: set[int] = set()
    for indices in indices_by_canonico.values():
        if len(indices) < 2:
            continue
        winner = min(
            indices,
            key=lambda idx: _canonical_priority(decisions[idx], ai_selected_flags[idx]),
        )
        duplicate_indices.update(idx for idx in indices if idx != winner)
    return duplicate_indices


def _canonical_priority(decision: dict[str, Any], ai_selected: bool) -> tuple[int, float, float, int]:
    price = decision.get('current_price')
    try:
        price_value = float(price) if price not in (None, '') else float('inf')
    except (TypeError, ValueError):
        price_value = float('inf')
    return (
        0 if ai_selected else 1,
        -_score(decision),
        price_value,
        int(decision.get('offer_id') or 0),
    )


def _contains_blocked_editorial_theme(decision: dict[str, Any]) -> bool:
    haystack_parts = [
        decision.get('rewritten_title'),
        decision.get('rewritten_caption_whatsapp'),
        decision.get('rewritten_caption_telegram'),
        decision.get('reason'),
    ]
    for action in decision.get('blacklist_actions') or []:
        if isinstance(action, dict):
            haystack_parts.extend([action.get('term'), action.get('normalized_term'), action.get('theme')])
        else:
            haystack_parts.append(action)
    haystack = _normalize_text(' '.join(str(part or '') for part in haystack_parts))
    return any(_normalize_text(term) in haystack for term in BLOCKED_EDITORIAL_TERMS)


def _ai_selection_key(decision: dict[str, Any]) -> tuple[int, float, int]:
    position = decision.get('batch_position')
    if isinstance(position, int) and position > 0:
        normalized_position = position
    else:
        normalized_position = 1_000_000
    return (normalized_position, -_score(decision), int(decision.get('offer_id') or 0))


def _sort_key(decision: dict[str, Any]) -> tuple[float, int, int]:
    return (-_score(decision), _marketplace_priority(decision.get('marketplace_code')), int(decision.get('offer_id') or 0))


def _score(decision: dict[str, Any]) -> float:
    value = decision.get('ai_score')
    if value is None:
        component_values = [
            decision.get('conversion_score'),
            decision.get('relevance_score'),
            decision.get('discount_quality_score'),
            decision.get('audience_fit_score'),
        ]
        scores = [float(component) for component in component_values if component is not None]
        return sum(scores) / len(scores) if scores else 0.0
    return float(value)


def _marketplace_priority(marketplace_code: Any) -> int:
    order = {marketplace: index for index, marketplace in enumerate(DEFAULT_TARGET_DISTRIBUTION)}
    return order.get(_normalize_marketplace_code(marketplace_code), len(order))


def _normalize_marketplace_code(value: Any) -> str:
    code = str(value or '').strip().lower().replace('-', '_')
    return MARKETPLACE_ALIASES.get(code, code)


def _normalize_text(value: str) -> str:
    replacements = str.maketrans({'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'é': 'e', 'ê': 'e', 'í': 'i', 'ó': 'o', 'ô': 'o', 'õ': 'o', 'ú': 'u', 'ç': 'c'})
    return value.lower().translate(replacements).replace('-', ' ')
