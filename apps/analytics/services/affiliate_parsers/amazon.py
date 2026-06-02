import csv
import hashlib
import io
import unicodedata
from collections import defaultdict
from datetime import date
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

# Aliases tolerantes (pt-BR oficial + en). Header normalizado para ASCII lower.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'asin': ('asin',),
    'title': (
        'produto', 'titulo', 'nome', 'product title', 'name', 'title',
    ),
    'tracking_id': (
        'numero de rastreamento', 'tracking id', 'associate tag', 'tag',
    ),
    'clicks': ('cliques', 'clicks'),
    'shipped': (
        'produtos enviados', 'items shipped', 'shipped',
    ),
    'ordered': (
        'produtos pedidos', 'items ordered', 'ordered', 'orders',
    ),
    'revenue': (
        'receita de produtos enviados', 'receita solicitada',
        'shipped revenue', 'ordered revenue', 'revenue',
    ),
    'commission': (
        'ganhos totais', 'ganhos de produtos enviados',
        'total earnings', 'earnings', 'commission', 'commission income',
    ),
}


def parse_amazon_tsv(
    payload: bytes,
    *,
    period_start: date,
    period_end: date,
    filename: str = '',
    commit: bool = True,
) -> BatchResult:
    """Parseia relatório Amazon Associates por ASIN (TSV/CSV).

    O painel Associates não inclui data nem canal nos exports — `period_start`
    e `period_end` precisam ser informados externamente pelo operador.

    Schema esperado (relatório por ASIN, Brasil pt-BR):
        ASIN | Produto | Cliques | Produtos pedidos | Produtos enviados |
        Receita... | Ganhos totais | ...

    Tolerante a aliases para suportar também o relatório agrupado por
    Tracking ID — nesse caso ASIN fica ausente e o parser ignora as linhas
    com warning explícito (use relatório por ASIN).

    Observações:
    - Channel sempre null (Amazon não expõe origem do clique no relatório).
    - Granularidade: 1 conversão por ASIN, agregando o período inteiro.
    """
    if period_start is None or period_end is None:
        raise ValueError('period_start e period_end são obrigatórios.')
    if period_start > period_end:
        period_start, period_end = period_end, period_start

    text = _decode_payload(payload)
    payload_sha256 = hashlib.sha256(payload).hexdigest()

    existing = AffiliateImportBatch.objects.filter(
        source=AffiliateSource.AMAZON,
        payload_sha256=payload_sha256,
    ).first()
    if existing:
        raise DuplicatePayloadError(existing)

    dialect = _detect_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError('Arquivo vazio ou sem cabeçalho.')

    field_map = _build_field_map(reader.fieldnames)
    if 'asin' not in field_map:
        raise ValueError(
            'Coluna ASIN ausente. Exporte o relatório com agrupamento por '
            'ASIN no painel Amazon Associates (ex: Ganhos → ASIN).'
        )
    if 'commission' not in field_map:
        raise ValueError(
            'Coluna de ganhos/comissão ausente no relatório. '
            f'Cabeçalho recebido: {reader.fieldnames}'
        )

    aggregated: dict[str, dict] = defaultdict(
        lambda: {
            'clicks': 0,
            'conversions': 0,
            'revenue_brl': Decimal('0'),
            'commission_brl': Decimal('0'),
            'tracking_ids': set(),
            'title': '',
        }
    )
    tracking_id_seen: set[str] = set()

    for row in reader:
        asin = _get(row, field_map, 'asin').strip().upper()
        if not asin:
            continue

        bucket = aggregated[asin]
        bucket['clicks'] += _to_int(_get(row, field_map, 'clicks'))
        # Preferência: produtos enviados (definitivo) > pedidos (mais agressivo)
        shipped = _to_int(_get(row, field_map, 'shipped'))
        ordered = _to_int(_get(row, field_map, 'ordered'))
        bucket['conversions'] += shipped or ordered
        bucket['revenue_brl'] += _to_decimal(_get(row, field_map, 'revenue'))
        bucket['commission_brl'] += _to_decimal(_get(row, field_map, 'commission'))

        title = _get(row, field_map, 'title').strip()
        if title and not bucket['title']:
            bucket['title'] = title

        tracking_id = _get(row, field_map, 'tracking_id').strip()
        if tracking_id:
            bucket['tracking_ids'].add(tracking_id)
            tracking_id_seen.add(tracking_id)

    if not aggregated:
        raise ValueError('Nenhuma linha com ASIN encontrada no arquivo.')

    marketplace = Marketplace.objects.filter(code=AMAZON_MARKETPLACE_CODE).first()
    if marketplace is None:
        raise ValueError("Marketplace 'amazon' não cadastrado.")

    expected_tag = (marketplace.affiliate_tag or '').strip()
    warnings: list[str] = []
    if expected_tag and tracking_id_seen:
        unknown = sorted(t for t in tracking_id_seen if t != expected_tag)
        if unknown:
            warnings.append(
                f'Tracking IDs divergentes de "{expected_tag}": {", ".join(unknown)}'
            )

    asin_offers = _resolve_amazon_offers(set(aggregated.keys()))

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

        for asin, bucket in aggregated.items():
            offer = asin_offers.get(asin)
            if offer is None:
                unresolved_asins.append(asin)

            lookup = {
                'source': AffiliateSource.AMAZON,
                'period_start': period_start,
                'period_end': period_end,
            }
            if offer is not None:
                lookup['offer'] = offer
                lookup['external_ref'] = ''
            else:
                lookup['offer'] = None
                lookup['external_ref'] = asin

            AffiliateConversion.objects.update_or_create(
                defaults={
                    'social_channel': None,
                    'product_title': bucket['title'][:255],
                    'clicks': bucket['clicks'],
                    'conversions': bucket['conversions'],
                    'revenue_brl': bucket['revenue_brl'],
                    'commission_brl': bucket['commission_brl'],
                    'batch': batch,
                },
                **lookup,
            )
            imported += 1

        if unresolved_asins:
            warnings.append(
                f'ASINs sem oferta cadastrada ({len(unresolved_asins)}): '
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


def _detect_dialect(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters='\t,;')
    except csv.Error:
        return csv.excel_tab


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
    cleaned = ' '.join(name.strip().split()).lower()
    decomposed = unicodedata.normalize('NFKD', cleaned)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _get(row: dict, field_map: dict[str, str], key: str) -> str:
    column = field_map.get(key)
    if not column:
        return ''
    return row.get(column) or ''


def _to_int(raw: str) -> int:
    raw = (raw or '').strip()
    if not raw:
        return 0
    cleaned = raw.replace('.', '').replace(',', '').replace(' ', '')
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _to_decimal(raw: str) -> Decimal:
    raw = (raw or '').strip()
    if not raw:
        return Decimal('0')
    cleaned = raw.replace('R$', '').replace(' ', '')
    if ',' in cleaned and cleaned.rfind(',') > cleaned.rfind('.'):
        # pt-BR: 1.234,56
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
