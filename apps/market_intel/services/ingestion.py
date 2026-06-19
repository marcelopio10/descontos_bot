from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.market_intel.services.parser import parse_observed_message

# Fields returned by parser v2 that map to model fields
PARSER_V2_FIELDS = (
    'parcelamento', 'parcelado_sem_juros', 'pix', 'pix_desconto_pct',
    'cashback', 'cashback_valor', 'menor_preco', 'cupom_tipo',
    'emoji_densidade', 'emojis_top', 'tem_headline', 'tem_de_por',
    'tem_cta', 'cta_termos', 'tipo_midia', 'tamanho_mensagem',
    'usa_caixa_alta', 'usa_negrito',
    'marketplace_dominio_desconhecido', 'programa_entrega', 'marca',
)


def import_observed_messages(payload: dict[str, Any]) -> dict[str, int]:
    if not payload.get('enabled'):
        return {'created': 0, 'updated': 0, 'skipped': 0}

    created = 0
    updated = 0
    skipped = 0
    for item in payload.get('messages') or []:
        try:
            was_created = _upsert_message(item)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if was_created:
            created += 1
        else:
            updated += 1
    return {'created': created, 'updated': updated, 'skipped': skipped}


def _upsert_message(item: dict[str, Any]) -> bool:
    group_jid = str(item['group_jid'])
    if not group_jid.endswith('@g.us'):
        raise ValueError('group_jid inválido')
    sender_hash = str(item['sender_hash'])
    if len(sender_hash) != 64:
        raise ValueError('sender_hash inválido')

    group, _ = ObservedWhatsAppGroup.objects.update_or_create(
        jid=group_jid,
        defaults={'name': str(item.get('group_subject') or group_jid)},
    )
    existing_message = ObservedWhatsAppMessage.objects.filter(
        group=group,
        external_message_id=str(item['message_id']),
    ).only('id').first()
    text = str(item.get('text') or '')
    urls = [str(url) for url in (item.get('urls') or []) if isinstance(url, str)]
    parsed = parse_observed_message(text, has_image=bool(item.get('has_image')), urls=urls)

    defaults = {
        'sender_hash': sender_hash,
        'sent_at': _parse_dt(str(item['sent_at'])),
        'collected_at': _parse_dt(str(item['collected_at'])),
        'text': text,
        'urls': urls,
        'has_image': bool(item.get('has_image')),
        'raw_type': str(item.get('raw_type') or ''),
        # v1 fields
        'parsed_marketplace': parsed['marketplace'],
        'parsed_price': _decimal_or_none(parsed['price']),
        'parsed_original_price': _decimal_or_none(parsed['original_price']),
        'parsed_discount_pct': _decimal_or_none(parsed['discount_pct']),
        'parsed_coupon': parsed['coupon'],
        'editorial_labels': parsed['labels'],
        'scraper_hints': parsed['scraper_hints'],
    }

    # v2 fields from parser
    for field in PARSER_V2_FIELDS:
        value = parsed.get(field)
        if field == 'emoji_densidade' and value is not None:
            value = Decimal(str(value))
        defaults[field] = _convert_v2_field(field, value)

    # Engagement fields (P0-1) — from wa_service when available
    engagement_fields = (
        'reacoes', 'visualizacoes', 'encaminhamentos', 'comentarios',
        'repostado', 'qtd_repostagens', 'fixado',
    )
    for field in engagement_fields:
        if field in item:
            value = item[field]
            if value is not None or existing_message is None:
                defaults[field] = value

    _, created = ObservedWhatsAppMessage.objects.update_or_create(
        group=group,
        external_message_id=str(item['message_id']),
        defaults=defaults,
    )
    return created


def _convert_v2_field(field: str, value: Any) -> Any:
    """Convert parser output to model field type."""
    if field in ('pix', 'cashback', 'menor_preco', 'parcelado_sem_juros',
                 'tem_headline', 'tem_de_por', 'tem_cta', 'usa_caixa_alta', 'usa_negrito',
                 'repostado'):
        return value  # already bool | None
    if field in ('parcelamento', 'tamanho_mensagem'):
        return value  # int | None
    if field in ('pix_desconto_pct', 'cashback_valor', 'emoji_densidade'):
        return _decimal_or_none(value) if isinstance(value, (str, Decimal)) else value
    if field in ('emojis_top', 'cta_termos'):
        return value if isinstance(value, list) else []
    # Str fields: cupom_tipo, tipo_midia, marketplace_dominio_desconhecido, programa_entrega, marca
    return str(value) if value is not None else ''


def _parse_dt(value: str):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f'datetime inválido: {value}')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _decimal_or_none(value: Decimal | str | None) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None