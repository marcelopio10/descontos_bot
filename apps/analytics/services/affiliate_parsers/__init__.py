from dataclasses import dataclass, field
from datetime import date

from apps.analytics.models import AffiliateImportBatch


class DuplicatePayloadError(ValueError):
    """Payload (sha256) já importado em batch anterior."""

    def __init__(self, existing_batch: AffiliateImportBatch):
        self.existing_batch = existing_batch
        super().__init__(
            f'Este payload já foi importado no lote #{existing_batch.id} '
            f'em {existing_batch.created_at:%Y-%m-%d %H:%M}.'
        )


@dataclass
class BatchResult:
    batch: AffiliateImportBatch
    imported: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
