import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.analytics.models import (
    AffiliateConversion,
    AffiliateImportBatch,
    AffiliateSource,
)
from apps.analytics.services.affiliate_parsers import BatchResult, DuplicatePayloadError
from apps.analytics.services.channel_codes import expand_short_channel_code
from apps.offers.models import Offer


ML_MARKETPLACE_CODES = ('mercadolivre', 'mercado_livre')

SUBID_PATTERN = re.compile(r'^dbot_(?P<channel>[a-z0-9_]+?)_(?P<offer_id>\d+)$')

SUBID_KEYS = ('matt_word', 'subid', 'sub_id', 'tag', 'tracking_id')
DATE_KEYS = ('date', 'report_date', 'day', 'data')
CLICK_KEYS = ('clicks', 'cliques', 'click_count')
CONVERSION_KEYS = ('conversions', 'orders', 'sales', 'conversoes', 'pedidos')
REVENUE_KEYS = ('revenue', 'gmv', 'sales_amount', 'amount', 'receita')
COMMISSION_KEYS = (
    'commission',
    'commission_amount',
    'commissions',
    'earnings',
    'comissao',
    'comissão',
)


def parse_mercadolivre_payload(
    payload: bytes | str,
    *,
    filename: str = '',
    commit: bool = True,
) -> BatchResult:
    """Parseia payload JSON copiado do painel ML Afiliados (DevTools).

    Formato esperado: lista de items ou dict com lista em alguma chave comum
    (`results`, `items`, `data`, `rows`). Cada item agrupa por SubID + dia.
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

    items = _extract_items(data)
    if not items:
        raise ValueError('Nenhum item encontrado no payload (esperado lista de conversões).')

    aggregated: dict[tuple[int, int | None, date], dict] = defaultdict(
        lambda: {
            'clicks': 0,
            'conversions': 0,
            'revenue_brl': Decimal('0'),
            'commission_brl': Decimal('0'),
            'subid_raw': '',
        }
    )

    warnings: list[str] = []
    unresolved_offers: list[int] = []
    unresolved_subids: list[str] = []
    skipped = 0
    period_start: date | None = None
    period_end: date | None = None

    offer_ids: set[int] = set()
    channel_cache: dict[str, int | None] = {}

    parsed_items: list[tuple[date, int | None, int | None, str, dict]] = []

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            warnings.append(f'Item ignorado (não é dict): {item!r}')
            continue

        subid_raw = _first_string(item, SUBID_KEYS).strip()
        try:
            report_date = _parse_date(_first_string(item, DATE_KEYS))
        except ValueError as exc:
            skipped += 1
            warnings.append(f'Data inválida ({exc}) — item: {_brief(item)}')
            continue

        match = SUBID_PATTERN.match(subid_raw) if subid_raw else None
        offer_id: int | None = None
        channel_short: str = ''
        if match:
            offer_id = int(match.group('offer_id'))
            channel_short = match.group('channel')
            offer_ids.add(offer_id)
        else:
            unresolved_subids.append(subid_raw or '(vazio)')

        parsed_items.append((report_date, offer_id, None, channel_short, item))

        period_start = report_date if period_start is None else min(period_start, report_date)
        period_end = report_date if period_end is None else max(period_end, report_date)

    offers_by_id = {
        offer.id: offer
        for offer in Offer.objects.select_related('marketplace').filter(
            id__in=offer_ids,
            marketplace__code__in=ML_MARKETPLACE_CODES,
        )
    }

    for report_date, offer_id, _unused, channel_short, item in parsed_items:
        if offer_id is None or offer_id not in offers_by_id:
            skipped += 1
            if offer_id is not None:
                unresolved_offers.append(offer_id)
            continue

        channel_id: int | None
        if channel_short in channel_cache:
            channel_id = channel_cache[channel_short]
        else:
            channel = expand_short_channel_code(channel_short)
            channel_id = channel.id if channel else None
            channel_cache[channel_short] = channel_id
            if channel is None and channel_short:
                warnings.append(f'Canal não resolvido para sufixo "{channel_short}"')

        key = (offer_id, channel_id, report_date)
        bucket = aggregated[key]
        bucket['clicks'] += _first_int(item, CLICK_KEYS)
        bucket['conversions'] += _first_int(item, CONVERSION_KEYS)
        bucket['revenue_brl'] += _first_decimal(item, REVENUE_KEYS)
        bucket['commission_brl'] += _first_decimal(item, COMMISSION_KEYS)
        if not bucket['subid_raw']:
            bucket['subid_raw'] = _first_string(item, SUBID_KEYS).strip()

    if unresolved_subids:
        warnings.append(
            f'SubIDs fora do padrão dbot_<canal>_<offer_id> ({len(unresolved_subids)}): '
            + ', '.join(sorted(set(unresolved_subids))[:20])
        )
    if unresolved_offers:
        warnings.append(
            f'IDs de oferta ML não encontrados ({len(unresolved_offers)}): '
            + ', '.join(str(i) for i in sorted(set(unresolved_offers))[:20])
        )

    imported = 0

    with transaction.atomic():
        batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.MERCADO_LIVRE,
            period_start=period_start,
            period_end=period_end,
            raw_filename=filename or '',
            payload_sha256=payload_sha256,
            notes='',
        )

        for (offer_id, channel_id, report_date), bucket in aggregated.items():
            AffiliateConversion.objects.update_or_create(
                offer_id=offer_id,
                social_channel_id=channel_id,
                source=AffiliateSource.MERCADO_LIVRE,
                report_date=report_date,
                defaults={
                    'subid': bucket['subid_raw'],
                    'clicks': bucket['clicks'],
                    'conversions': bucket['conversions'],
                    'revenue_brl': bucket['revenue_brl'],
                    'commission_brl': bucket['commission_brl'],
                    'batch': batch,
                },
            )
            imported += 1

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


def _extract_items(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('results', 'items', 'data', 'rows', 'records', 'subids'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _first_string(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in item and item[key] is not None:
            return str(item[key])
    return ''


def _first_int(item: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in item and item[key] is not None:
            try:
                return int(item[key])
            except (TypeError, ValueError):
                try:
                    return int(float(item[key]))
                except (TypeError, ValueError):
                    return 0
    return 0


def _first_decimal(item: dict, keys: tuple[str, ...]) -> Decimal:
    for key in keys:
        if key in item and item[key] is not None:
            try:
                return Decimal(str(item[key]))
            except InvalidOperation:
                return Decimal('0')
    return Decimal('0')


def _parse_date(raw: str) -> date:
    raw = (raw or '').strip()
    if not raw:
        raise ValueError('data vazia')
    if 'T' in raw:
        raw = raw.split('T', 1)[0]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(raw)


def _brief(item: dict, limit: int = 120) -> str:
    text = json.dumps(item, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + '…'
