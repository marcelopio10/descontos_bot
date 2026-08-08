from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.curation.services.hermes_runner import HermesRunner, HermesProfileRunner

from ..models import CouponCandidate, CouponDecision
from .observer_editorial import build_coupon_editorial_pattern
from .posts import build_coupon_post, build_coupon_telegram_post


class CouponFakeRunner:
    def run(self, payload):
        return {
            'schema_version': 'coupon-1.0',
            'decisions': [
                {
                    'candidate_hash': row['candidate_hash'],
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'relevance_score': 70,
                    'benefit_score': 70,
                    'reliability_score': 70,
                    'frustration_risk_score': 5,
                    'reason': 'evidência suficiente para homologação',
                }
                for row in payload['candidates']
            ],
        }


def build_payload(candidates, observer_pattern):
    return {
        'schema_version': 'coupon-1.0',
        'editorial_pattern': observer_pattern,
        'criteria': ['relevance', 'benefit', 'reliability', 'restrictions', 'frustration_risk', 'information_quality'],
        'candidates': [
            {
                'candidate_hash': c.candidate_hash,
                'marketplace': c.marketplace,
                'activation_code': c.activation_code,
                'benefit': c.benefit,
                'minimum_purchase': str(c.minimum_purchase or ''),
                'maximum_discount': str(c.maximum_discount or ''),
                'restrictions': c.restrictions,
                'valid_until': c.valid_until.isoformat() if c.valid_until else None,
                'evidence': c.evidence[:2000],
            }
            for c in candidates
        ],
    }


def curate_candidates(run, candidates, channel, runner: HermesRunner | None = None, observer_pattern=None):
    pattern = observer_pattern or build_coupon_editorial_pattern()
    payload = build_payload(candidates, pattern)
    runner = runner or HermesProfileRunner(profile_name='descontos-bot')
    try:
        output = runner.run(payload)
    except Exception as exc:
        run.errors_json = [*run.errors_json, f'curadoria IA indisponível: {exc}']
        run.status = 'failed'
        run.save(update_fields=['errors_json', 'status', 'updated_at'])
        return []
    decisions = {str(row.get('candidate_hash')): row for row in output.get('decisions', []) if isinstance(row, dict)}
    selected = []
    with transaction.atomic():
        for candidate in candidates:
            row = decisions.get(candidate.candidate_hash, {})
            approved = row.get('classification') == 'approved'
            decision = CouponDecision.objects.create(
                candidate=candidate,
                classification='approved' if approved else 'rejected',
                selected=False,
                relevance_score=_decimal(row.get('relevance_score')),
                benefit_score=_decimal(row.get('benefit_score')),
                reliability_score=_decimal(row.get('reliability_score')),
                frustration_risk_score=_decimal(row.get('frustration_risk_score')),
                reason=str(row.get('reason') or 'IA não aprovou ou não retornou decisão'),
                whatsapp_post=build_coupon_post(candidate, channel) if approved else '',
                telegram_post=build_coupon_telegram_post(candidate, channel) if approved else '',
                editorial_structure_json=pattern,
            )
            if approved:
                selected.append((candidate, decision))
        selected.sort(key=lambda pair: _rank(pair[1]), reverse=True)
        selected = selected[:5]
        for _, decision in selected:
            decision.selected = True
            decision.save(update_fields=['selected', 'updated_at'])
    run.selected_count = len(selected)
    run.status = 'completed'
    run.save(update_fields=['selected_count', 'status', 'updated_at'])
    return [candidate for candidate, _ in selected]


def _decimal(value):
    try:
        return Decimal(str(value)) if value is not None else None
    except Exception:
        return None


def _rank(decision):
    return sum(float(getattr(decision, field) or 0) for field in ('reliability_score', 'relevance_score', 'benefit_score')) - float(decision.frustration_risk_score or 0)
