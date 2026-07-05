from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import floor
from typing import Any, Iterable

from apps.curation.services.ai_schema import SAFETY_RISK_FLAGS

DEFAULT_TARGET_DISTRIBUTION: dict[str, float] = {
    'mercadolivre': 0.4,
    'amazon': 0.3,
    'shopee': 0.3,
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
    selected_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for original in decisions:
        decision = dict(original)
        decision['marketplace_code'] = _normalize_marketplace_code(decision.get('marketplace_code'))
        ai_selected = bool(decision.get('selected_for_batch'))
        if ai_selected and _is_eligible(decision, min_ai_score=min_ai_score):
            selected_candidates.append(decision)
        else:
            decision['selected_for_batch'] = False
            decision['batch_position'] = None
            rejected.append(decision)

    selected = sorted(selected_candidates, key=_ai_selection_key)[:batch_size]
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
