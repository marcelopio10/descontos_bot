import csv
import hashlib
import io
import unicodedata
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
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


SHOPEE_MARKETPLACE_CODE = 'shopee'

# Prefixo curto -> prefixo completo do SocialChannel.code, mesma convenção de
# `_short_channel_code()` em `apps/analytics/services/link_builder.py`
# (replicada aqui, sem importar entre apps, para reconstruir o canal a partir
# do subId2 gravado no link Shopee no momento do envio — Tarefa 4.1).
_SUBID_CHANNEL_PREFIX_MAP = {
    'wa': 'whatsapp',
    'tg': 'telegram',
}

# ATENÇÃO — melhor estimativa, não validada contra um export real:
# não tivemos acesso a um relatório de conversão real da Shopee ao escrever
# este parser (Tarefa 2.6). Os nomes de coluna abaixo foram inferidos da
# documentação pública do Shopee Affiliate Program. Confira contra o export
# real na primeira vez que for usado e ajuste os aliases se necessário
# (mesmo espírito de `COLUMN_ALIASES` em affiliate_parsers/amazon.py).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    'order_id': (
        'order id', 'id do pedido', 'purchase id', 'id da compra',
    ),
    'item_id': (
        'item id', 'id do item', 'product id', 'id do produto',
    ),
    'shop_id': (
        'shop id', 'id da loja', 'seller id', 'id do vendedor',
    ),
    'title': (
        'item name', 'nome do item', 'product name', 'nome do produto', 'produto',
    ),
    'click_time': (
        'click time', 'hora do clique', 'data do clique',
    ),
    'conversion_time': (
        'conversion time', 'hora da conversao', 'purchase time',
        'data da compra', 'order time', 'data do pedido',
    ),
    'status': (
        'status', 'order status', 'status do pedido', 'conversion status',
        'status da conversao',
    ),
    'quantity': (
        'quantity', 'quantidade', 'qty',
    ),
    'clicks': (
        'clicks', 'cliques',
    ),
    'revenue': (
        'actual amount', 'valor', 'order amount', 'valor do pedido',
        'gmv', 'sales amount', 'valor da venda', 'valor do item',
    ),
    'commission': (
        'commission', 'comissao', 'estimated commission',
        'commission amount', 'valor da comissao', 'net commission',
        'total commission',
    ),
    'sub_id1': ('sub id 1', 'subid1', 'sub_id1'),
    'sub_id2': ('sub id 2', 'subid2', 'sub_id2'),
    'sub_id3': ('sub id 3', 'subid3', 'sub_id3'),
    'sub_id4': ('sub id 4', 'subid4', 'sub_id4'),
    'sub_id5': ('sub id 5', 'subid5', 'sub_id5'),
}

CONFIRMED_STATUS_VALUES = {'confirmed', 'confirmado', 'approved', 'aprovado', 'completed', 'concluido'}
PENDING_STATUS_VALUES = {'pending', 'pendente', 'unconfirmed', 'nao confirmado'}
REJECTED_STATUS_VALUES = {
    'cancelled', 'canceled', 'cancelado', 'invalid', 'invalido',
    'rejected', 'rejeitado', 'failed', 'falhou',
}


def parse_shopee_report(
    payload: bytes,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    filename: str = '',
    commit: bool = True,
    include_pending: bool = False,
) -> BatchResult:
    """Parseia o relatório de conversão do Shopee Affiliate Program (CSV/TSV).

    RESTR-04: Shopee é a única fonte de afiliado com relatório exportável
    oficialmente (ML e Amazon exigem entrada manual — ver
    `ingest_affiliate_amazon.py`/`ingest_affiliate_mercadolivre.py`).

    ATENÇÃO — melhor estimativa de schema: não validamos este parser contra
    um export real do painel Shopee. As colunas aceitas (`COLUMN_ALIASES`)
    são a melhor hipótese com base na documentação pública do Shopee
    Affiliate Program. Confira o cabeçalho do primeiro export real e ajuste
    os aliases/campos obrigatórios se divergir.

    Período: se `period_start`/`period_end` não forem informados, o parser
    tenta derivá-los do min/max das colunas de data (`conversion_time` ou,
    na ausência dela, `click_time`) presentes no arquivo — diferente do
    Amazon (sem datas no arquivo, sempre manual) e mais parecido com o ML
    (datas vêm no próprio payload).

    Status: por padrão, só linhas com status "confirmado"/"confirmed" (ou
    sem coluna de status — nesse caso assume-se que o export já é só de
    conversões confirmadas) entram na agregação. `include_pending=True`
    inclui também linhas "pendente"/"pending". Linhas canceladas/inválidas
    são sempre ignoradas.

    SubID: se o arquivo tiver a coluna subId2 (ver
    `apps/marketplaces/services/shopee_link_generator.py` para o esquema de
    canal/campanha — `subId2 = canal`), o parser tenta reconstruir
    `AffiliateConversion.social_channel` a partir dela: prefixo curto
    `wa_`/`tg_` (mesmo formato gerado por `_short_channel_code()` em
    `apps/analytics/services/link_builder.py` no momento do envio) vira
    `whatsapp_`/`telegram_`, e o resultado é buscado em `SocialChannel.code`.
    Quando resolve, o canal é persistido; quando não (subId2 ausente, prefixo
    desconhecido — ex. `ig_`/`site` — ou código sem `SocialChannel`
    correspondente), `social_channel` fica `null` — degradação aceitável, não
    erro. O resumo do batch reporta quantos itens resolveram canal vs não.

    Chave de agregação: `Offer.external_id` da Shopee é `"{itemId}:{shopId}"`
    (ver `apps/marketplaces/services/shopee_normalizer.py`). Se o relatório
    trouxer só Item ID (sem Shop ID), a resolução por catálogo é best-effort
    (só resolve se o Item ID for inequívoco entre os itens Shopee cadastrados).
    """
    text = _decode_payload(payload)
    payload_sha256 = hashlib.sha256(payload).hexdigest()

    existing = AffiliateImportBatch.objects.filter(
        source=AffiliateSource.SHOPEE,
        payload_sha256=payload_sha256,
    ).first()
    if existing:
        raise DuplicatePayloadError(existing)

    dialect = _detect_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError('Arquivo vazio ou sem cabeçalho.')

    field_map = _build_field_map(reader.fieldnames)
    if 'item_id' not in field_map:
        raise ValueError(
            'Coluna de Item ID ausente. Cabeçalho recebido: '
            f'{reader.fieldnames}. Se o export real usa outro nome de '
            'coluna, adicione o alias em COLUMN_ALIASES '
            '(apps/analytics/services/affiliate_parsers/shopee.py).'
        )
    if 'commission' not in field_map:
        raise ValueError(
            'Coluna de comissão ausente no relatório. '
            f'Cabeçalho recebido: {reader.fieldnames}'
        )

    aggregated: dict[str, dict] = defaultdict(
        lambda: {
            'conversions': 0,
            'clicks': 0,
            'revenue_brl': Decimal('0'),
            'commission_brl': Decimal('0'),
            'title': '',
            'shop_id': '',
            'sub_id2': '',
        }
    )
    date_values: list[date] = []
    status_unknown_seen: set[str] = set()
    rows_rejected = 0
    rows_pending_excluded = 0
    rows_without_item_id = 0

    for row in reader:
        item_id = _get(row, field_map, 'item_id').strip()
        if not item_id:
            rows_without_item_id += 1
            continue

        status_raw = _get(row, field_map, 'status').strip()
        status_norm = _normalize_header(status_raw) if status_raw else ''
        if status_norm:
            if status_norm in REJECTED_STATUS_VALUES:
                rows_rejected += 1
                continue
            if status_norm in PENDING_STATUS_VALUES and not include_pending:
                rows_pending_excluded += 1
                continue
            if (
                status_norm not in CONFIRMED_STATUS_VALUES
                and status_norm not in PENDING_STATUS_VALUES
            ):
                status_unknown_seen.add(status_raw)
                # Status desconhecido: inclui por padrão (mesma postura tolerante
                # do resto do parser), mas avisa no resumo.

        shop_id = _get(row, field_map, 'shop_id').strip()
        key = f'{item_id}:{shop_id}' if shop_id else item_id

        bucket = aggregated[key]
        if shop_id:
            bucket['shop_id'] = shop_id

        quantity = _to_int(_get(row, field_map, 'quantity')) or 1
        bucket['conversions'] += quantity
        bucket['clicks'] += _to_int(_get(row, field_map, 'clicks'))
        bucket['revenue_brl'] += _to_decimal(_get(row, field_map, 'revenue'))
        bucket['commission_brl'] += _to_decimal(_get(row, field_map, 'commission'))

        title = _get(row, field_map, 'title').strip()
        if title and not bucket['title']:
            bucket['title'] = title

        sub_id2 = _get(row, field_map, 'sub_id2').strip()
        if sub_id2 and not bucket['sub_id2']:
            bucket['sub_id2'] = sub_id2

        row_date = _parse_row_date(row, field_map)
        if row_date is not None:
            date_values.append(row_date)

    if not aggregated:
        if rows_rejected or rows_pending_excluded:
            raise ValueError(
                'Nenhuma linha restou após o filtro de status '
                f'(rejeitadas={rows_rejected}, pendentes_excluidas={rows_pending_excluded}). '
                'Use --include-pending se quiser contabilizar conversões pendentes.'
            )
        raise ValueError('Nenhuma linha com Item ID válido encontrada no arquivo.')

    resolved_period_start, resolved_period_end = _resolve_period(
        period_start, period_end, date_values,
    )

    offer_by_full_key, offer_by_item_id = _resolve_shopee_offers(aggregated.keys())

    warnings: list[str] = []
    if status_unknown_seen:
        warnings.append(
            'Valores de status não reconhecidos (incluídos por padrão — '
            'confira se representam conversão confirmada): '
            + ', '.join(sorted(status_unknown_seen)[:10])
        )
    if rows_rejected:
        warnings.append(f'Linhas com status cancelado/inválido ignoradas: {rows_rejected}')
    if rows_pending_excluded:
        warnings.append(
            f'Linhas com status pendente ignoradas: {rows_pending_excluded} '
            '(use --include-pending para contabilizá-las)'
        )
    if rows_without_item_id:
        warnings.append(f'Linhas sem Item ID ignoradas: {rows_without_item_id}')

    imported = 0
    skipped = 0
    unresolved: list[str] = []
    ambiguous: list[str] = []
    channel_resolved_count = 0
    channel_unresolved_count = 0

    with transaction.atomic():
        batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.SHOPEE,
            period_start=resolved_period_start,
            period_end=resolved_period_end,
            raw_filename=filename or '',
            payload_sha256=payload_sha256,
            notes='',
        )

        for key, bucket in aggregated.items():
            offer, ambiguous_item = _lookup_offer(
                key, bucket, offer_by_full_key, offer_by_item_id,
            )
            if ambiguous_item:
                ambiguous.append(key)
            if offer is None:
                unresolved.append(key)

            social_channel = None
            if bucket['sub_id2']:
                social_channel = _resolve_social_channel_from_subid(bucket['sub_id2'])
                if social_channel is not None:
                    channel_resolved_count += 1
                else:
                    channel_unresolved_count += 1

            lookup = {
                'source': AffiliateSource.SHOPEE,
                'period_start': resolved_period_start,
                'period_end': resolved_period_end,
            }
            if offer is not None:
                lookup['offer'] = offer
                lookup['external_ref'] = ''
            else:
                lookup['offer'] = None
                lookup['external_ref'] = key

            AffiliateConversion.objects.update_or_create(
                defaults={
                    'social_channel': social_channel,
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

        if unresolved:
            warnings.append(
                f'Itens Shopee sem oferta cadastrada ({len(unresolved)}): '
                + ', '.join(sorted(unresolved)[:20])
                + ('…' if len(unresolved) > 20 else '')
            )
        if ambiguous:
            warnings.append(
                'Item ID sem Shop ID no relatório casou com mais de uma oferta '
                f'cadastrada (ambíguo, tratado como não resolvido): '
                + ', '.join(sorted(ambiguous)[:20])
            )
        if channel_resolved_count or channel_unresolved_count:
            warnings.append(
                f'SubID de canal (subId2): {channel_resolved_count} item(ns) '
                f'resolveram social_channel, {channel_unresolved_count} não '
                'resolveram (subId2 ausente/prefixo desconhecido/canal não '
                'encontrado — social_channel permanece null nesses casos).'
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
        period_start=resolved_period_start,
        period_end=resolved_period_end,
    )


def _resolve_social_channel_from_subid(sub_id2: str) -> SocialChannel | None:
    """Reconstrói o `SocialChannel` a partir do subId2 (canal) do relatório.

    O subId2 é gravado no momento do envio no formato curto produzido por
    `_short_channel_code()` em `apps/analytics/services/link_builder.py`
    (ex.: `wa_principal`, `tg_homolog`). Replica a mesma regra aqui — sem
    importar entre apps — para não acoplar `apps.analytics` a
    `apps.analytics.services.link_builder` por um detalhe de formatação:
    prefixo `wa_` vira `whatsapp_`, `tg_` vira `telegram_`, e o resultado é
    buscado em `SocialChannel.code`.

    Retorna `None` (degradação aceitável, não erro) quando o subId2 está
    vazio, tem prefixo desconhecido (ex.: `ig_`, `site`, campanhas sem
    canal) ou não casa com nenhum `SocialChannel` cadastrado.
    """
    value = (sub_id2 or '').strip().lower()
    if not value:
        return None
    prefix, separator, rest = value.partition('_')
    if not separator or not rest:
        return None
    full_prefix = _SUBID_CHANNEL_PREFIX_MAP.get(prefix)
    if not full_prefix:
        return None
    candidate_code = f'{full_prefix}_{rest}'
    return SocialChannel.objects.filter(code=candidate_code).first()


def _resolve_period(
    period_start: date | None,
    period_end: date | None,
    date_values: list[date],
) -> tuple[date, date]:
    if period_start is not None and period_end is not None:
        if period_start > period_end:
            period_start, period_end = period_end, period_start
        return period_start, period_end

    if date_values:
        return min(date_values), max(date_values)

    raise ValueError(
        'Não foi possível determinar o período: o arquivo não tem coluna de '
        'data reconhecida (conversion_time/click_time) e --period-start/'
        '--period-end não foram informados.'
    )


def _lookup_offer(
    key: str,
    bucket: dict,
    offer_by_full_key: dict[str, Offer],
    offer_by_item_id: dict[str, list[Offer]],
) -> tuple[Offer | None, bool]:
    shop_id = bucket.get('shop_id') or ''
    if shop_id:
        offer = offer_by_full_key.get(key.upper())
        return offer, False

    candidates = offer_by_item_id.get(key.upper(), [])
    if len(candidates) == 1:
        return candidates[0], False
    if len(candidates) > 1:
        return None, True
    return None, False


def _resolve_shopee_offers(
    keys,
) -> tuple[dict[str, Offer], dict[str, list[Offer]]]:
    offers = list(
        Offer.objects.select_related('marketplace').filter(
            marketplace__code=SHOPEE_MARKETPLACE_CODE,
        )
    )
    offer_by_full_key: dict[str, Offer] = {}
    offer_by_item_id: dict[str, list[Offer]] = defaultdict(list)
    for offer in offers:
        external_id = (offer.external_id or '').strip()
        if not external_id:
            continue
        offer_by_full_key[external_id.upper()] = offer
        item_id_part = external_id.split(':', 1)[0]
        if item_id_part:
            offer_by_item_id[item_id_part.upper()].append(offer)
    return offer_by_full_key, dict(offer_by_item_id)


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


_DATE_FORMATS = (
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d',
    '%d/%m/%Y %H:%M:%S',
    '%d/%m/%Y %H:%M',
    '%d/%m/%Y',
    '%m/%d/%Y %H:%M:%S',
    '%m/%d/%Y',
)


def _parse_row_date(row: dict, field_map: dict[str, str]) -> date | None:
    raw = _get(row, field_map, 'conversion_time').strip() or _get(row, field_map, 'click_time').strip()
    if not raw:
        return None
    # Timestamp UNIX (segundos ou millis), caso o export traga epoch em vez de string.
    if raw.isdigit():
        try:
            value = int(raw)
            if value > 10**12:  # millis
                value //= 1000
            return datetime.fromtimestamp(value).date()
        except (ValueError, OSError, OverflowError):
            return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None
