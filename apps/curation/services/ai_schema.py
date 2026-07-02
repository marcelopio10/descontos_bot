from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INPUT_SCHEMA_VERSION = '1.0'
OUTPUT_SCHEMA_VERSION = '1.0'
ALLOWED_CLASSIFICATIONS = {'approved', 'rejected', 'improper'}
SAFETY_RISK_FLAGS = {'adult_content', 'weapon', 'obscene'}
REQUIRED_DECISION_FIELDS = {
    'offer_id',
    'classification',
    'selected_for_batch',
    'batch_position',
    'conversion_score',
    'relevance_score',
    'discount_quality_score',
    'audience_fit_score',
    'reason',
    'rewritten_title',
    'rewritten_caption_whatsapp',
    'rewritten_caption_telegram',
    'image_required',
    'image_decision',
    'blacklist_actions',
    'risk_flags',
}


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: list[str]

    def raise_for_errors(self) -> None:
        if not self.is_valid:
            raise ValueError('; '.join(self.errors))


def validate_agent_input(payload: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if payload.get('schema_version') != INPUT_SCHEMA_VERSION:
        errors.append('schema_version de entrada inválida')
    run = payload.get('run')
    if not isinstance(run, dict):
        errors.append('run obrigatório')
    else:
        for field in ('run_id', 'mode', 'channel_code', 'batch_size', 'target_distribution'):
            if field not in run:
                errors.append(f'run.{field} obrigatório')
    if not isinstance(payload.get('editorial_policy'), dict):
        errors.append('editorial_policy obrigatório')
    if not isinstance(payload.get('baseline_rules'), dict):
        errors.append('baseline_rules obrigatório')
    if not isinstance(payload.get('observer_context'), dict):
        errors.append('observer_context obrigatório')
    offers = payload.get('offers')
    if not isinstance(offers, list):
        errors.append('offers deve ser lista')
    else:
        for index, offer in enumerate(offers):
            if not isinstance(offer, dict):
                errors.append(f'offers[{index}] deve ser objeto')
                continue
            for field in ('offer_id', 'title', 'marketplace_code', 'current_price', 'discount_pct', 'baseline'):
                if field not in offer:
                    errors.append(f'offers[{index}].{field} obrigatório')
    return ValidationResult(not errors, errors)


def validate_agent_output(payload: dict[str, Any], *, expected_offer_ids: set[int] | None = None) -> ValidationResult:
    errors: list[str] = []
    if payload.get('schema_version') != OUTPUT_SCHEMA_VERSION:
        errors.append('schema_version de saída inválida')
    decisions = payload.get('decisions')
    if not isinstance(decisions, list):
        errors.append('decisions deve ser lista')
        return ValidationResult(False, errors)

    seen_positions: set[int] = set()
    selected_marketplaces: dict[str, int] = {}
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            errors.append(f'decisions[{index}] deve ser objeto')
            continue
        missing = REQUIRED_DECISION_FIELDS - set(decision)
        if missing:
            errors.append(f'decisions[{index}] campos ausentes: {sorted(missing)}')
            continue

        offer_id = decision.get('offer_id')
        if expected_offer_ids is not None and offer_id not in expected_offer_ids:
            errors.append(f'decisions[{index}].offer_id inesperado: {offer_id}')

        classification = decision.get('classification')
        selected = bool(decision.get('selected_for_batch'))
        risk_flags = set(decision.get('risk_flags') or [])
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(f'decisions[{index}].classification inválida: {classification}')
        if classification == 'improper' and selected:
            errors.append(f'decisions[{index}] imprópria não pode ser selecionada')
        if risk_flags & SAFETY_RISK_FLAGS and selected:
            errors.append(f'decisions[{index}] risco proibido não pode ser selecionado')
        if selected:
            if not str(decision.get('rewritten_caption_whatsapp') or '').strip():
                errors.append(f'decisions[{index}] selecionada sem caption WhatsApp')
            if not str(decision.get('rewritten_caption_telegram') or '').strip():
                errors.append(f'decisions[{index}] selecionada sem caption Telegram')
            position = decision.get('batch_position')
            if not isinstance(position, int) or position <= 0:
                errors.append(f'decisions[{index}].batch_position inválida')
            elif position in seen_positions:
                errors.append(f'decisions[{index}].batch_position duplicada: {position}')
            else:
                seen_positions.add(position)
            marketplace_code = str(decision.get('marketplace_code') or '').strip()
            if marketplace_code:
                selected_marketplaces[marketplace_code] = selected_marketplaces.get(marketplace_code, 0) + 1
    declared_distribution = payload.get('actual_distribution')
    if isinstance(declared_distribution, dict) and selected_marketplaces:
        for marketplace, count in selected_marketplaces.items():
            if declared_distribution.get(marketplace) != count:
                errors.append(
                    f'actual_distribution.{marketplace}={declared_distribution.get(marketplace)} não bate com selecionados={count}'
                )
    return ValidationResult(not errors, errors)
