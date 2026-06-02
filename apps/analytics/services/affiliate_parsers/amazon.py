import csv
import hashlib
import io
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
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


AMAZON_MARKETPLACE_CODE = 'amazon'

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'date': ('date', 'data', 'report date', 'report_date'),
    'asin': ('asin',),
    'title': ('title', 'titulo', 'product title', 'name'),
    'tracking_id': ('tracking id', 'tracking_id', 'tag', 'associate tag'),
    'clicks': ('clicks', 'cliques'),
    'shipped': ('items shipped', 'shipped', 'ordered', 'orders', 'pedidos'),
    'revenue': ('revenue', 'receita', 'ordered revenue', 'shipped revenue'),
    'commission': (
        'commission',
        'commission income',
        'earnings',
        'comissao',
        'comissão',
        'total earnings',
    ),
}


def parse_amazon_tsv(
    payload: bytes,
    *,
    filename: str = '',
    commit: bool = True,
) -> BatchResult:
    """Parseia Earnings Report do Amazon Associates (TSV UTF-8).

    Amazon não expõe canal de origem no Earnings Report — todas as conversões
    ficam com social_channel=null e source='amazon'.
    """
    text = _decode_payload(payload)
    payload_sha256 = hashlib.sha256(payload).hexdigest()

    existing = AffiliateImportBatch.objects.filter(
        source=AffiliateSource.AMAZON,
        payload_sha256=payload_sha256,
    ).first()
    if existing:
        raise DuplicatePayloadError(existing)

    dialect, has_header = _detect_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError('Arquivo vazio ou sem cabeçalho.')

    field_map = _build_field_map(reader.fieldnames)
    _require_columns(field_map, ('date', 'asin', 'commission'))

    marketplace = Marketplace.objects.filter(code=AMAZON_MARKETPLACE_CODE).first()
    if marketplace is None:
        raise ValueError("Marketplace 'amazon' não cadastrado.")

    aggregated: dict[tuple[str, date], dict] = defaultdict(
        lambda: {
            'clicks': 0,
            'conversions': 0,
            'revenue_brl': Decimal('0'),
            'commission_brl': Decimal('0'),
            'tracking_ids': set(),
            'title': '',
        }
    )

    warnings: list[str] = []
    period_start: date | None = None
    period_end: date | None = None
    tracking_id_seen: set[str] = set()

    for row in reader:
        try:
            report_date = _parse_date(_get(row, field_map, 'date'))
        except ValueError as exc:
            warnings.append(f'Data inválida: {exc} — linha: {row}')
            continue

        asin = (_get(row, field_map, 'asin') or '').strip().upper()
        if not asin:
            warnings.append(f'Linha sem ASIN: {row}')
            continue

        key = (asin, report_date)
        bucket = aggregated[key]
        bucket['clicks'] += _to_int(_get(row, field_map, 'clicks'))
        bucket['conversions'] += _to_int(_get(row, field_map, 'shipped'))
        bucket['revenue_brl'] += _to_decimal(_get(row, field_map, 'revenue'))
        bucket['commission_brl'] += _to_decimal(_get(row, field_map, 'commission'))
        title = (_get(row, field_map, 'title') or '').strip()
        if title and not bucket['title']:
            bucket['title'] = title
        tracking_id = (_get(row, field_map, 'tracking_id') or '').strip()
        if tracking_id:
            bucket['tracking_ids'].add(tracking_id)
            tracking_id_seen.add(tracking_id)

        period_start = report_date if period_start is None else min(period_start, report_date)
        period_end = report_date if period_end is None else max(period_end, report_date)

    expected_tag = (marketplace.affiliate_tag or '').strip()
    if expected_tag and tracking_id_seen:
        unknown = sorted(t for t in tracking_id_seen if t != expected_tag)
        if unknown:
            warnings.append(
                f'Tracking IDs divergentes de "{expected_tag}": {", ".join(unknown)}'
            )

    asin_offers = _resolve_amazon_offers({asin for asin, _ in aggregated.keys()})

    imported = 0
    skipped = 0
    unresolved_asins: list[str] = []

    with transaction.atomic():
        batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.AMAZON,
            period_start=period_start,
            period_end=period_end,
            raw_filename=filename or '',
            payload_sha256=payload_sha256,
            notes='',
        )

        for (asin, report_date), bucket in aggregated.items():
            offer = asin_offers.get(asin)
            if offer is None:
                skipped += 1
                unresolved_asins.append(asin)
                continue

            subid = next(iter(bucket['tracking_ids']), '')
            AffiliateConversion.objects.update_or_create(
                offer=offer,
                social_channel=None,
                source=AffiliateSource.AMAZON,
                report_date=report_date,
                defaults={
                    'subid': subid,
                    'clicks': bucket['clicks'],
                    'conversions': bucket['conversions'],
                    'revenue_brl': bucket['revenue_brl'],
                    'commission_brl': bucket['commission_brl'],
                    'batch': batch,
                },
            )
            imported += 1

        if unresolved_asins:
            warnings.append(
                f'ASINs sem oferta correspondente ({len(unresolved_asins)}): '
                + ', '.join(sorted(unresolved_asins)[:20])
                + ('…' if len(unresolved_asins) > 20 else '')
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


def _decode_payload(payload: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('Não foi possível decodificar o arquivo (esperado UTF-8 ou Latin-1).')


def _detect_dialect(text: str) -> tuple[csv.Dialect, bool]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters='\t,;')
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect = csv.excel_tab
        has_header = True
    return dialect, has_header


def _build_field_map(fieldnames: list[str]) -> dict[str, str]:
    normalized = {name: _normalize_header(name) for name in fieldnames}
    field_map: dict[str, str] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for original, norm in normalized.items():
            if norm in aliases:
                field_map[key] = original
                break
    return field_map


def _normalize_header(name: str) -> str:
    return ' '.join(name.strip().lower().split())


def _require_columns(field_map: dict[str, str], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in field_map]
    if missing:
        raise ValueError(
            f'Colunas obrigatórias ausentes no relatório Amazon: {", ".join(missing)}'
        )


def _get(row: dict, field_map: dict[str, str], key: str) -> str:
    column = field_map.get(key)
    if not column:
        return ''
    return row.get(column) or ''


def _parse_date(raw: str) -> date:
    raw = (raw or '').strip()
    if not raw:
        raise ValueError('vazia')
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(raw)


def _to_int(raw: str) -> int:
    raw = (raw or '').strip().replace('.', '').replace(',', '')
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _to_decimal(raw: str) -> Decimal:
    raw = (raw or '').strip()
    if not raw:
        return Decimal('0')
    cleaned = raw.replace('R$', '').replace(' ', '')
    if ',' in cleaned and cleaned.rfind(',') > cleaned.rfind('.'):
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '')
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal('0')


def _resolve_amazon_offers(asins: set[str]) -> dict[str, Offer]:
    if not asins:
        return {}
    upper_asins = {asin.upper() for asin in asins}
    by_asin = {
        offer.asin.upper(): offer
        for offer in Offer.objects.select_related('marketplace').filter(
            marketplace__code=AMAZON_MARKETPLACE_CODE,
            asin__in=upper_asins,
        )
        if offer.asin
    }
    missing = upper_asins - by_asin.keys()
    if missing:
        by_external = {
            (offer.external_id or '').upper(): offer
            for offer in Offer.objects.select_related('marketplace').filter(
                marketplace__code=AMAZON_MARKETPLACE_CODE,
                external_id__in=missing,
            )
        }
        for asin, offer in by_external.items():
            by_asin.setdefault(asin, offer)
    return by_asin
