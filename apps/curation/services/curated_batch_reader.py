from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem
from apps.distribution.models import SocialChannel


@dataclass(frozen=True)
class CuratedBatchReadResult:
    batch: CuratedBatch | None
    items: list[CuratedBatchItem]
    reason: str = ''

    @property
    def has_batch(self) -> bool:
        return self.batch is not None


def get_ready_curated_batch(channel: SocialChannel, *, allowed_modes: list[str] | None = None) -> CuratedBatchReadResult:
    now = timezone.now()
    qs = (
        CuratedBatch.objects
        .select_related('run', 'channel')
        .filter(channel=channel, status=CuratedBatch.Status.READY)
        .filter(expires_at__gt=now)
    )
    if allowed_modes:
        qs = qs.filter(run__mode__in=allowed_modes)
    batch = qs.order_by('created_at').first()
    if batch is None:
        return CuratedBatchReadResult(batch=None, items=[], reason='Nenhum lote curado pronto para este canal.')

    items = list(
        batch.items
        .select_related('offer__marketplace', 'decision')
        .filter(send_status=CuratedBatchItem.SendStatus.PENDING)
        .order_by('position')
    )
    if not items:
        return CuratedBatchReadResult(batch=None, items=[], reason='Lote curado pronto sem itens pendentes.')
    return CuratedBatchReadResult(batch=batch, items=items)
