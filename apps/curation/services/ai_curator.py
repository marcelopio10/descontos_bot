from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationBlacklistTerm, CurationDecision, CurationRun
from apps.curation.services.ai_prompt import build_ai_curation_payload
from apps.curation.services.ai_schema import validate_agent_input, validate_agent_output
from apps.curation.services.batch_optimizer import DEFAULT_TARGET_DISTRIBUTION, optimize_curation_batch
from apps.curation.services.blacklist_updates import add_curation_blacklist_term
from apps.curation.services.hermes_runner import FakeHermesRunner, HermesRunner, HermesRunnerError
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer

DEFAULT_AUDIT_DIR = Path('runtime/curation/ai_runs')


@dataclass(frozen=True)
class AICurationResult:
    run: CurationRun
    batch: CuratedBatch | None
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None


def prepare_ai_curation_batch(
    *,
    channel: SocialChannel,
    offers: list[Offer],
    runner: HermesRunner | None = None,
    mode: str = CurationRun.Mode.DRY_RUN,
    batch_size: int = 20,
    audit_dir: Path | str | None = None,
    public_json_dir: Path | str | None = None,
    observer_context: dict[str, Any] | None = None,
    target_distribution: dict[str, float] | None = None,
    profile_name: str = 'descontos.bot',
    model_provider: str = 'mock',
    model_name: str = 'fake-hermes-runner',
) -> AICurationResult:
    """Prepare and persist an AI-curated batch without sending anything.

    Sprint 4 intentionally accepts an injectable runner and defaults to a fake
    deterministic runner. Real Hermes execution is introduced in a later sprint.
    """
    target = target_distribution or DEFAULT_TARGET_DISTRIBUTION
    runner = runner or FakeHermesRunner()
    audit_path = Path(audit_dir) if audit_dir is not None else DEFAULT_AUDIT_DIR
    public_path = Path(public_json_dir) if public_json_dir is not None else None

    run = CurationRun.objects.create(
        channel=channel,
        status=CurationRun.Status.RUNNING,
        mode=mode,
        profile_name=profile_name,
        model_provider=model_provider,
        model_name=model_name,
        candidate_count=len(offers),
        selected_count=0,
        target_distribution_json=target,
        observer_context_json=observer_context or {},
        schema_version='1.0',
    )
    input_payload = build_ai_curation_payload(
        run=run,
        channel=channel,
        offers=offers,
        batch_size=batch_size,
        observer_context=observer_context,
        target_distribution=target,
    )
    input_validation = validate_agent_input(input_payload)
    if not input_validation.is_valid:
        _fail_run(run, '; '.join(input_validation.errors))
        return AICurationResult(run=run, batch=None, input_payload=input_payload, output_payload=None)

    run.baseline_summary_json = input_payload.get('baseline_summary') or {}
    run.input_json_path = str(_write_audit_json(audit_path, run.id, 'input', input_payload))
    run.save(update_fields=['baseline_summary_json', 'input_json_path', 'updated_at'])

    try:
        output_payload = runner.run(input_payload)
    except HermesRunnerError as exc:
        _fail_run(run, str(exc))
        return AICurationResult(run=run, batch=None, input_payload=input_payload, output_payload=None)
    except Exception as exc:  # pragma: no cover - defensive boundary around external runners
        _fail_run(run, f'erro inesperado no runner Hermes: {exc}')
        return AICurationResult(run=run, batch=None, input_payload=input_payload, output_payload=None)

    run.output_json_path = str(_write_audit_json(audit_path, run.id, 'output', output_payload))
    run.save(update_fields=['output_json_path', 'updated_at'])

    expected_offer_ids = {offer.id for offer in offers}
    output_validation = validate_agent_output(output_payload, expected_offer_ids=expected_offer_ids)
    if not output_validation.is_valid:
        _fail_run(run, '; '.join(output_validation.errors))
        return AICurationResult(run=run, batch=None, input_payload=input_payload, output_payload=output_payload)

    with transaction.atomic():
        decisions_by_offer_id = _persist_decisions(run, offers, output_payload, input_payload)
        optimized = optimize_curation_batch(output_payload.get('decisions') or [], batch_size=batch_size, target_distribution=target)

        if not optimized.selected:
            _fail_run(run, f'Nenhum item aprovado e selecionado pela IA para o lote (candidatas={len(offers)}; gate de segurança ou IA não selecionou itens)')
            return AICurationResult(run=run, batch=None, input_payload=input_payload, output_payload=output_payload)

        batch = CuratedBatch.objects.create(
            run=run,
            channel=channel,
            status=CuratedBatch.Status.READY,
            batch_size=len(optimized.selected),
            target_distribution_json=optimized.target_distribution,
            actual_distribution_json=optimized.actual_distribution,
            expires_at=timezone.now() + timezone.timedelta(hours=36),
        )
        for item in optimized.selected:
            offer_id = item['offer_id']
            decision = decisions_by_offer_id[offer_id]
            CuratedBatchItem.objects.create(
                batch=batch,
                decision=decision,
                offer=decision.offer,
                position=item['batch_position'],
                final_title=(item.get('rewritten_title') or decision.offer.title)[:500],
                final_caption_whatsapp=item.get('rewritten_caption_whatsapp') or '',
                final_caption_telegram=item.get('rewritten_caption_telegram') or '',
                final_image_url=decision.offer.image_url or '',
            )
            decision.is_selected_for_batch = True
            decision.save(update_fields=['is_selected_for_batch', 'updated_at'])

        run.status = CurationRun.Status.COMPLETED
        run.selected_count = len(optimized.selected)
        run.actual_distribution_json = optimized.actual_distribution
        run.save(update_fields=['status', 'selected_count', 'actual_distribution_json', 'updated_at'])

    run.refresh_from_db()
    batch.refresh_from_db()
    if public_path is not None:
        run.public_json_path = str(_write_public_json(public_path, run, batch))
        run.save(update_fields=['public_json_path', 'updated_at'])
        run.refresh_from_db()
    return AICurationResult(run=run, batch=batch, input_payload=input_payload, output_payload=output_payload)


def _persist_decisions(
    run: CurationRun,
    offers: list[Offer],
    output_payload: dict[str, Any],
    input_payload: dict[str, Any],
) -> dict[int, CurationDecision]:
    offers_by_id = {offer.id: offer for offer in offers}
    baselines_by_offer_id = {
        int(offer_payload['offer_id']): offer_payload.get('baseline') or {}
        for offer_payload in input_payload.get('offers') or []
        if offer_payload.get('offer_id') is not None
    }
    decisions_by_offer_id: dict[int, CurationDecision] = {}
    for raw_decision in output_payload.get('decisions') or []:
        offer_id = int(raw_decision['offer_id'])
        offer = offers_by_id[offer_id]
        baseline = baselines_by_offer_id.get(offer_id, {})
        decision = CurationDecision.objects.create(
            run=run,
            offer=offer,
            marketplace_code=str(raw_decision.get('marketplace_code') or (offer.marketplace.code if offer.marketplace_id else '')),
            baseline_score=_decimal_or_none(baseline.get('score')),
            baseline_classification=str(baseline.get('classification') or ''),
            baseline_decision=str(baseline.get('decision') or ''),
            ai_score=_decision_score(raw_decision),
            ai_classification=raw_decision.get('classification') or CurationDecision.Classification.REJECTED,
            conversion_score=_decimal_or_none(raw_decision.get('conversion_score')),
            relevance_score=_decimal_or_none(raw_decision.get('relevance_score')),
            discount_quality_score=_decimal_or_none(raw_decision.get('discount_quality_score')),
            audience_fit_score=_decimal_or_none(raw_decision.get('audience_fit_score')),
            decision_reason=str(raw_decision.get('reason') or ''),
            risk_flags_json=list(raw_decision.get('risk_flags') or []),
            observer_signals_json={},
            title_original=offer.title,
            title_rewritten=str(raw_decision.get('rewritten_title') or '')[:500],
            caption_rewritten=str(raw_decision.get('rewritten_caption_whatsapp') or ''),
            image_analysis_json={'required': bool(raw_decision.get('image_required')), 'decision': raw_decision.get('image_decision')},
            blacklist_terms_json=list(raw_decision.get('blacklist_actions') or []),
            raw_ai_json=raw_decision,
            is_selected_for_batch=False,
        )
        _apply_blacklist_actions(run, decision, raw_decision)
        decisions_by_offer_id[offer_id] = decision
    return decisions_by_offer_id


def _apply_blacklist_actions(run: CurationRun, decision: CurationDecision, raw_decision: dict[str, Any]) -> None:
    for action in raw_decision.get('blacklist_actions') or []:
        if isinstance(action, dict):
            term = str(action.get('term') or action.get('normalized_term') or '').strip()
            source = action.get('source') or CurationBlacklistTerm.Source.AI_TEXT_MODERATION
        else:
            term = str(action or '').strip()
            source = CurationBlacklistTerm.Source.AI_TEXT_MODERATION
        if not term:
            continue
        add_curation_blacklist_term(
            term=term,
            source=source,
            offer=decision.offer,
            decision=decision,
            run=run,
        )


def _decision_score(raw_decision: dict[str, Any]) -> Decimal | None:
    values = [
        raw_decision.get('conversion_score'),
        raw_decision.get('relevance_score'),
        raw_decision.get('discount_quality_score'),
        raw_decision.get('audience_fit_score'),
    ]
    numeric = [Decimal(str(value)) for value in values if value is not None]
    if not numeric:
        return None
    return sum(numeric) / Decimal(len(numeric))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == '':
        return None
    return Decimal(str(value))


def _write_public_json(public_dir: Path, run: CurationRun, batch: CuratedBatch) -> Path:
    public_dir.mkdir(parents=True, exist_ok=True)
    decisions = []
    for decision in run.decisions.select_related('offer').order_by('-is_selected_for_batch', '-ai_score', 'offer_id'):
        batch_item = getattr(decision, 'batch_item', None)
        decisions.append(
            {
                'offer_id': decision.offer_id,
                'marketplace_code': decision.marketplace_code,
                'classification': decision.ai_classification,
                'selected': decision.is_selected_for_batch,
                'position': batch_item.position if batch_item else None,
                'score': float(decision.ai_score) if decision.ai_score is not None else None,
                'title': decision.title_rewritten or decision.title_original,
                'reason': decision.decision_reason,
                'risk_flags': decision.risk_flags_json,
            }
        )
    payload = {
        'schema_version': run.schema_version,
        'generated_at': timezone.now().isoformat(),
        'run': {
            'id': run.id,
            'status': run.status,
            'mode': run.mode,
            'channel_code': run.channel.code,
            'candidate_count': run.candidate_count,
            'selected_count': run.selected_count,
        },
        'batch': {
            'id': batch.id,
            'status': batch.status,
            'batch_size': batch.batch_size,
            'target_distribution': batch.target_distribution_json,
            'actual_distribution': batch.actual_distribution_json,
        },
        'decisions': decisions,
    }
    path = public_dir / f'curation-run-{run.id}.json'
    path.write_text(json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    return path


def _write_audit_json(audit_dir: Path, run_id: int | None, label: str, payload: dict[str, Any]) -> Path:
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f'curation-run-{run_id}-{label}.json'
    path.write_text(json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    return path


def _fail_run(run: CurationRun, message: str) -> None:
    run.status = CurationRun.Status.FAILED
    run.error_message = message[:4000]
    run.selected_count = 0
    run.save(update_fields=['status', 'error_message', 'selected_count', 'updated_at'])
