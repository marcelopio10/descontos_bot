from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.curation.services.ai_schema import OUTPUT_SCHEMA_VERSION


class HermesRunnerError(RuntimeError):
    """Raised when a Hermes curation run cannot produce a usable payload."""


class HermesRunner(Protocol):
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return structured JSON for the curation payload."""
        ...


@dataclass
class FakeHermesRunner:
    """Deterministic Sprint-4 runner used before real Hermes integration.

    It deliberately does not call Hermes, external APIs or delivery services. The
    real profile runner is introduced later; this fake exercises the orchestration,
    schema validation and persistence path safely.
    """

    should_fail: bool = False
    forced_payload: dict[str, Any] | None = None

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.should_fail:
            raise HermesRunnerError('falha simulada do Hermes')
        if self.forced_payload is not None:
            return self.forced_payload

        decisions: list[dict[str, Any]] = []
        for offer in payload.get('offers') or []:
            score = _score_from_offer(offer)
            offer_id = offer.get('offer_id')
            title = str(offer.get('title') or '').strip() or f'Oferta {offer_id}'
            marketplace_code = str(offer.get('marketplace_code') or '').strip()
            decisions.append(
                {
                    'offer_id': offer_id,
                    'marketplace_code': marketplace_code,
                    'classification': 'approved',
                    'selected_for_batch': False,
                    'batch_position': None,
                    'conversion_score': score,
                    'relevance_score': score,
                    'discount_quality_score': score,
                    'audience_fit_score': score,
                    'reason': 'Aprovada pelo runner mockado para validar a orquestração.',
                    'rewritten_title': title[:500],
                    'rewritten_caption_whatsapp': f'{title} — oferta selecionada com curadoria.',
                    'rewritten_caption_telegram': f'{title} — oferta selecionada com curadoria.',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            )
        return {
            'schema_version': OUTPUT_SCHEMA_VERSION,
            'decisions': decisions,
            'actual_distribution': {},
        }


def _score_from_offer(offer: dict[str, Any]) -> float:
    baseline_value = offer.get('baseline')
    baseline = baseline_value if isinstance(baseline_value, dict) else {}
    score = baseline.get('score')
    if score is None:
        score = offer.get('discount_pct') or 0
    return round(float(score), 2)
