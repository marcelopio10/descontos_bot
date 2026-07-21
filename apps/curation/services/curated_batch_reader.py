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
    """Retorna o lote `ready` mais antigo que ainda tenha itens pendentes.

    Lotes `ready` sem itens pendentes (ex.: todos os itens ficaram `skipped`
    pela janela de silêncio) são pulados em vez de bloquear a busca — do
    contrário, um único lote exaurido no início da fila impede
    indefinidamente o consumo de lotes mais novos com itens de verdade
    (achado real: 30+ lotes de curadoria IA descartados sem uso em ~25h por
    causa desse gargalo, antes desta correção).
    """
    now = timezone.now()
    qs = (
        CuratedBatch.objects
        .select_related('run', 'channel')
        .filter(channel=channel, status=CuratedBatch.Status.READY)
        .filter(expires_at__gt=now)
    )
    if allowed_modes:
        qs = qs.filter(run__mode__in=allowed_modes)

    for batch in qs.order_by('created_at'):
        items = list(
            batch.items
            .select_related('offer__marketplace', 'decision')
            .filter(send_status=CuratedBatchItem.SendStatus.PENDING)
            .order_by('position')
        )
        if items:
            return CuratedBatchReadResult(batch=batch, items=items)

    if qs.exists():
        return CuratedBatchReadResult(batch=None, items=[], reason='Lote curado pronto sem itens pendentes.')
    return CuratedBatchReadResult(batch=None, items=[], reason='Nenhum lote curado pronto para este canal.')
