from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Protocol

from apps.marketplaces.services.commercial_opportunity import CommercialOpportunity
from apps.marketplaces.services.source_contracts import SourceQuery, SourceResult, SourceState


class OpportunitySource(Protocol):
    def execute(self, query: SourceQuery) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class ExecutionReport:
    results: tuple[SourceResult, ...]
    offers: tuple[dict[str, Any], ...]


def execute_opportunities(opportunities: tuple[CommercialOpportunity, ...], *, source: OpportunitySource) -> ExecutionReport:
    results: list[SourceResult] = []
    offers: list[dict[str, Any]] = []
    for opportunity in opportunities:
        query = SourceQuery(
            marketplace=opportunity.marketplace,
            query_text=opportunity.query_text,
            opportunity_id=_opportunity_id(opportunity),
            source_kind=opportunity.source_kind,
            query_hash=_query_hash(opportunity.query_text, opportunity.marketplace),
            brand=opportunity.brand,
            category_code=opportunity.category_code,
            price_band=opportunity.price_band,
        )
        try:
            payloads = tuple(source.execute(query) or ())
        except Exception as exc:
            results.append(SourceResult(query=query, state=SourceState.FAILED, error_code='source_exception', error_message=type(exc).__name__))
            continue
        if not payloads:
            results.append(SourceResult(query=query, state=SourceState.EMPTY))
            continue
        enriched = tuple(_attach_provenance(payload, query) for payload in payloads)
        results.append(SourceResult(query=query, state=SourceState.EXECUTED, offers=enriched))
        offers.extend(enriched)
    return ExecutionReport(tuple(results), tuple(offers))


def _attach_provenance(payload: dict[str, Any], query: SourceQuery) -> dict[str, Any]:
    result = dict(payload)
    result['search_provenance'] = {
        'source_kind': query.source_kind,
        'query_text': query.query_text,
        'opportunity_id': query.opportunity_id,
        'query_hash': query.query_hash,
        'marketplace': query.marketplace,
    }
    return result


def _query_hash(query_text: str, marketplace: str) -> str:
    return hashlib.sha256(f'{marketplace}:{query_text}'.encode()).hexdigest()[:16]


def _opportunity_id(opportunity: CommercialOpportunity) -> str:
    return f'{opportunity.marketplace}:{opportunity.source_kind}:{_query_hash(opportunity.query_text, opportunity.marketplace)}'
