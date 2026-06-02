import hashlib
import json
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.analytics.models import (
    AffiliateConversion,
    AffiliateImportBatch,
    AffiliateSource,
)
from apps.analytics.services.affiliate_parsers import BatchResult, DuplicatePayloadError
from apps.offers.models import Offer


ML_MARKETPLACE_CODES = ('mercadolivre', 'mercado_livre')


def parse_mercadolivre_payload(
    payload: bytes | str,
    *,
    filename: str = '',
    commit: bool = True,
) -> BatchResult:
    """Parseia payload JSON do painel ML Afiliados (DevTools).

    Schema real do XHR (validado em 2026-06):

        {
            "item_list": [
                {
                    "product": "...",
                    "entity_id": "MLB...",   ← casa com Offer.external_id
                    "quantity": 3,           ← conversões (pedidos)
                    "earnings": 23.34,       ← comissão R$
                    "total_sales": 142.23,   ← receita R$
                    "fee": 0.20              ← % comissão (não usado)
                    ...
                }
            ],
            "filter_time_range": "1777766400000--1780358400000",  ← millis UNIX
            ...
        }

    Observações:
    - ML não expõe SubID por linha → `social_channel` sempre null.
    - ML não expõe cliques → `clicks = 0`.
    - Granularidade: 1 linha por entity_id, agregando o período inteiro.
    """
    raw_bytes = payload if isinstance(payload, bytes) else payload.encode('utf-8')
    payload_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode('utf-8-sig') if isinstance(payload, bytes) else payload

    existing = AffiliateImportBatch.objects.filter(
        source=AffiliateSource.MERCADO_LIVRE,
        payload_sha256=payload_sha256,
    ).first()
    if existing:
        raise DuplicatePayloadError(existing)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON inválido: {exc}') from exc

    if not isinstance(data, dict):
        raise ValueError('Payload raiz precisa ser um objeto JSON.')

    items = data.get('item_list')
    if not isinstance(items, list) or not items:
        raise ValueError('Campo "item_list" ausente ou vazio no payload.')

    period_start, period_end = _extract_period(data)

    entity_ids = {
        str(item.get('entity_id', '')).strip().upper()
        for item in items
        if isinstance(item, dict) and item.get('entity_id')
    }
    offers_by_external = {
        (offer.external_id or '').upper(): offer
        for offer in Offer.objects.select_related('marketplace').filter(
            marketplace__code__in=ML_MARKETPLACE_CODES,
            external_id__in=entity_ids,
        )
    }

    warnings: list[str] = []
    unresolved: list[str] = []
    imported = 0
    skipped = 0

    with transaction.atomic():
        batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.MERCADO_LIVRE,
            period_start=period_start,
            period_end=period_end,
            raw_filename=filename or '',
            payload_sha256=payload_sha256,
            notes='',
        )

        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                warnings.append(f'Item ignorado (não é dict): {item!r}')
                continue

            entity_id = str(item.get('entity_id', '')).strip().upper()
            if not entity_id:
                skipped += 1
                warnings.append(f'Item sem entity_id: {_brief(item)}')
                continue

            offer = offers_by_external.get(entity_id)
            if offer is None:
                unresolved.append(entity_id)

            quantity = _to_int(item.get('quantity'))
            earnings = _to_decimal(item.get('earnings'))
            total_sales = _to_decimal(item.get('total_sales'))
            product_title = str(item.get('product') or '')[:255]

            lookup = {
                'source': AffiliateSource.MERCADO_LIVRE,
                'period_start': period_start,
                'period_end': period_end,
            }
            if offer is not None:
                lookup['offer'] = offer
                lookup['external_ref'] = ''
            else:
                lookup['offer'] = None
                lookup['external_ref'] = entity_id

            AffiliateConversion.objects.update_or_create(
                defaults={
                    'social_channel': None,
                    'product_title': product_title,
                    'clicks': 0,
                    'conversions': quantity,
                    'revenue_brl': total_sales,
                    'commission_brl': earnings,
                    'batch': batch,
                },
                **lookup,
            )
            imported += 1

        if unresolved:
            warnings.append(
                f'Entity IDs ML sem oferta cadastrada ({len(unresolved)}): '
                + ', '.join(sorted(set(unresolved))[:20])
                + ('…' if len(set(unresolved)) > 20 else '')
            )

        batch.rows_imported = imported
        batch.rows_skipped = skipped
        batch.notes = '\n'.join(warnings)
        batch.save(update_fields=['rows_imported', 'rows_skipped', 'notes'])

        if not commit:
            transaction.set_rollback(True)

    return BatchResult(
        batch=batch,
        imported=imported,
        skipped=skipped,
        warnings=warnings,
        period_start=period_start,
        period_end=period_end,
    )


def _extract_period(data: dict) -> tuple[date, date]:
    raw = data.get('filter_time_range') or ''
    if not raw or '--' not in raw:
        raise ValueError(
            'Campo "filter_time_range" ausente — necessário para identificar o período.'
        )
    start_str, _, end_str = raw.partition('--')
    try:
        start_ms = int(start_str)
        end_ms = int(end_str)
    except ValueError as exc:
        raise ValueError(f'"filter_time_range" inválido: {raw}') from exc

    start = datetime.fromtimestamp(start_ms / 1000, tz=dt_timezone.utc).date()
    end = datetime.fromtimestamp(end_ms / 1000, tz=dt_timezone.utc).date()
    if start > end:
        start, end = end, start
    return start, end


def _to_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal('0')
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal('0')


def _brief(item: dict, limit: int = 120) -> str:
    text = json.dumps(item, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + '…'
