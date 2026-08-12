from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SourceState(StrEnum):
    PLANNED = 'planned'
    EXECUTED = 'executed'
    BLOCKED = 'blocked'
    FAILED = 'failed'
    EMPTY = 'empty'
    PARTIAL = 'partial'


@dataclass(frozen=True)
class SourceQuery:
    marketplace: str
    query_text: str
    opportunity_id: str
    source_kind: str
    query_hash: str
    brand: str = ''
    category_code: str = ''
    price_band: str = ''


@dataclass(frozen=True)
class SourceResult:
    query: SourceQuery
    state: SourceState
    offers: tuple[dict[str, Any], ...] = ()
    error_code: str = ''
    error_message: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        return self.state in {SourceState.EXECUTED, SourceState.PARTIAL} and bool(self.offers)


@dataclass(frozen=True)
class SourceHealth:
    marketplace: str
    available: bool
    reason: str = ''
