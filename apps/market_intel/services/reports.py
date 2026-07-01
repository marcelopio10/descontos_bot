import re
import unicodedata
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import timezone

from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage

LOCAL_TZ = ZoneInfo('America/Sao_Paulo')

# v1 allowlists (unchanged)
ALLOWED_LABELS = {
    'urgencia',
    'prova_social',
    'cupom',
    'imagem',
    'ate_50',
    'ate_100',
    'ate_300',
    'acima_300',
}
ALLOWED_RAW_TYPES = {'conversation', 'extendedTextMessage', 'imageMessage', 'videoMessage', 'documentMessage'}
ALLOWED_HINTS = {
    'categoria:casa/cozinha',
    'categoria:moda',
    'categoria:tecnologia',
    'categoria:beleza',
    'categoria:esporte',
    'categoria:brinquedos',
    'categoria:pet',
    'termo:air fryer',
    'termo:cafeteira',
    'termo:fone',
    'termo:monitor',
    'termo:tenis',
    'faixa_preco:ate_100',
    'faixa_preco:ate_300',
    'faixa_preco:acima_300',
    'desconto:desconto_30',
    'desconto:desconto_50',
    'desconto:desconto_70',
}
ALLOWED_MARKETPLACES = {
    'amazon', 'mercadolivre', 'shopee', 'magalu', 'aliexpress',
    'shein', 'americanas', 'casas_bahia', 'centauro', 'netshoes', 'kabum',
    'desconhecido',
}

# v2 labels (new dimensions)
V2_LABELS = {
    'desconto_30', 'desconto_50', 'desconto_70',
    'parcelado_sem_juros', 'pix', 'cashback', 'menor_preco',
    'frete_gratis',
}
ALL_LABELS = ALLOWED_LABELS | V2_LABELS

# CTA terms (must match parser)
CTA_TERMS_SET = {
    'corre', 'garante_ja', 'acabando', 'ultimas_unidades', 'so_hoje',
    'corra', 'nao_perca', 'aproveite',
}

# Media types
ALLOWED_MEDIA_TYPES = {'foto_oficial', 'banner_proprio', 'video', 'carrossel', 'texto'}

# Coupon types
ALLOWED_COUPON_TYPES = {'percentual', 'valor_fixo', 'frete_gratis'}

# Delivery programs
ALLOWED_DELIVERY_PROGRAMS = {'full', 'prime', 'frete_gratis'}

URL_OR_WHATSAPP_ID_RE = re.compile(
    r'https?://\S+|www\.\S+|[A-Za-z0-9_:+.-]+@(?:g\.us|s\.whatsapp\.net|lid)',
    re.IGNORECASE,
)
COUPON_RE = re.compile(r'^[A-Z0-9_-]{3,24}$')
PRICE_TEXT_RE = re.compile(r'R\$\s*[0-9\.]+,?\d*', re.IGNORECASE)
NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


def _normalize_url_for_match(url: str) -> str:
    raw_url = str(url or '').strip()
    parsed = urlparse(raw_url)
    if not parsed.netloc and raw_url and not raw_url.startswith('/'):
        parsed = urlparse(f'//{raw_url}')
    host = parsed.netloc.lower().removeprefix('www.')
    path = parsed.path.rstrip('/').lower()
    return f'{host}{path}' if host else ''


def _normalize_text_for_match(value: str) -> str:
    text = str(value or '').lower()
    text = ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )
    text = URL_OR_WHATSAPP_ID_RE.sub(' ', text)
    text = PRICE_TEXT_RE.sub(' ', text)
    text = NON_ALNUM_RE.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip()



def _extract_category(row: ObservedWhatsAppMessage) -> str:
    return next(
        (h.split(':', 1)[1] for h in (row.scraper_hints or []) if str(h).startswith('categoria:')),
        '',
    )


def _build_offer_index():
    from apps.offers.models import Offer

    offers = list(
        Offer.objects.select_related('category')
        .filter(is_active=True)
        .only('id', 'product_url', 'normalized_title', 'title', 'first_seen_at', 'category__code')
    )
    by_url = {}
    by_title = []
    for offer in offers:
        norm_url = _normalize_url_for_match(offer.product_url)
        if norm_url:
            by_url[norm_url] = offer
        title = _normalize_text_for_match(offer.normalized_title or offer.title)
        if title and len(title) >= 12:
            by_title.append((title, offer))
    return {'by_url': by_url, 'by_title': by_title}


def _match_own_offer(row: ObservedWhatsAppMessage, offer_index: dict):
    for url in row.urls or []:
        match = offer_index['by_url'].get(_normalize_url_for_match(url))
        if match:
            return match, 'url'
    observed_text = _normalize_text_for_match(row.text)
    observed_tokens = set(observed_text.split())
    if observed_text and len(observed_tokens) >= 4:
        for title, offer in offer_index['by_title']:
            title_tokens = set(title.split())
            if len(title_tokens) < 3:
                continue
            overlap = observed_tokens & title_tokens
            overlap_ratio = len(overlap) / len(title_tokens)
            if title in observed_text or overlap_ratio >= 0.75:
                return offer, 'titulo_normalizado'
    return None, ''


def _coverage_lag_hours(row: ObservedWhatsAppMessage, offer) -> float | None:
    if not offer or not getattr(offer, 'first_seen_at', None) or not row.sent_at:
        return None
    return round((offer.first_seen_at - row.sent_at).total_seconds() / 3600, 1)


def _detect_sazonalidade(rows: list[ObservedWhatsAppMessage]) -> list[dict]:
    counts = Counter()
    for row in rows:
        text = _normalize_text_for_match(row.text)
        local_date = row.sent_at.astimezone(LOCAL_TZ).date() if row.sent_at else None
        if 'black friday' in text or (local_date and local_date.month == 11 and local_date.day >= 20):
            counts['black_friday'] += 1
        if 'prime day' in text or 'prime ofertas' in text:
            counts['prime_day'] += 1
        if 'dia dos pais' in text:
            counts['dia_dos_pais'] += 1
        if 'dia das maes' in text:
            counts['dia_das_maes'] += 1
        if 'natal' in text or (local_date and local_date.month == 12 and local_date.day >= 10):
            counts['natal'] += 1
    return [{'evento': evento, 'count': count} for evento, count in counts.most_common()]


def generate_daily_report(report_date: date) -> MarketIntelDailyReport:
    window_start = datetime.combine(report_date, time.min, tzinfo=LOCAL_TZ).astimezone(dt_timezone.utc)
    window_end = datetime.combine(report_date, time.max, tzinfo=LOCAL_TZ).astimezone(dt_timezone.utc)
    messages = ObservedWhatsAppMessage.objects.select_related('group').filter(
        sent_at__gte=window_start,
        sent_at__lte=window_end,
    )
    summary = summarize_messages(messages)
    recommendations = build_recommendations(summary)
    opportunities = build_scraper_opportunities(messages)
    report, _ = MarketIntelDailyReport.objects.update_or_create(
        date=report_date,
        defaults={
            'window_start': window_start,
            'window_end': window_end,
            'groups_analyzed': summary['groups_analyzed'],
            'messages_analyzed': summary['messages_analyzed'],
            'summary_json': summary,
            'recommendations_json': recommendations,
            'scraper_opportunities_json': opportunities,
            'payload_version': '2.0',
        },
    )
    return report


# ---------------------------------------------------------------------------
# v1 aggregation (unchanged)
# ---------------------------------------------------------------------------

def summarize_messages(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    rows = list(messages)
    marketplace_counts = Counter(_sanitize_marketplace(row.parsed_marketplace) for row in rows)
    group_counts = Counter(_sanitize_public_text(row.group.name) for row in rows)
    label_counts: Counter[str] = Counter()
    for row in rows:
        label_counts.update(_allowed_values(row.editorial_labels or [], ALL_LABELS))
    return {
        'groups_analyzed': len({row.group_id for row in rows}),
        'messages_analyzed': len(rows),
        'top_groups': _counter_items(group_counts, 'group'),
        'top_marketplaces': _counter_items(marketplace_counts, 'marketplace'),
        'top_labels': _counter_items(label_counts, 'label'),
        'image_messages': sum(1 for row in rows if row.has_image),
        'coupon_messages': sum(1 for row in rows if row.parsed_coupon),
    }


def build_recommendations(summary: dict) -> list[dict]:
    recommendations: list[dict] = []
    if summary.get('coupon_messages', 0):
        recommendations.append({
            'type': 'copy',
            'title': 'Destacar cupom quando existir',
            'reason': 'Grupos monitorados usam cupom como gancho editorial recorrente.',
        })
    if summary.get('image_messages', 0):
        recommendations.append({
            'type': 'creative',
            'title': 'Priorizar ofertas com imagem forte',
            'reason': 'Amostra observada contém mensagens com imagem, útil para WhatsApp e Instagram.',
        })
    recommendations.append({
        'type': 'curation',
        'title': 'Usar achados como sinais agregados, não como fonte de ofertas',
        'reason': 'Mantém compliance e evita copiar links/copy de terceiros.',
    })
    return recommendations


def build_scraper_opportunities(messages: QuerySet[ObservedWhatsAppMessage]) -> list[dict]:
    hint_counts: Counter[str] = Counter()
    marketplace_counts: Counter[str] = Counter()
    for row in messages:
        hint_counts.update(_allowed_values(row.scraper_hints or [], ALLOWED_HINTS))
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        if marketplace != 'desconhecido':
            marketplace_counts[marketplace] += 1
    opportunities = []
    for hint, count in hint_counts.most_common(10):
        opportunities.append({
            'hint': hint,
            'count': count,
            'reason': 'Recorrência nos grupos monitorados.',
        })
    for marketplace, count in marketplace_counts.most_common(5):
        opportunities.append({
            'marketplace': marketplace,
            'count': count,
            'reason': 'Marketplace aparece nos grupos monitorados e deve ser comparado com cobertura própria.',
        })
    return opportunities


# ---------------------------------------------------------------------------
# v2 aggregation blocks (new dimensions)
# ---------------------------------------------------------------------------

def build_mecanica_preco(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P0-2: Price mechanics aggregation."""
    rows = list(messages)
    desconto_buckets = Counter()
    pix_count = 0
    parcelado_count = 0
    cashback_count = 0
    menor_preco_count = 0
    frete_gratis_count = 0
    cupom_por_tipo = Counter()
    por_marketplace: dict[str, dict] = {}
    por_categoria: dict[str, dict] = {}

    for row in rows:
        labels = set(row.editorial_labels or [])
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        category = ''
        for hint in (row.scraper_hints or []):
            if hint.startswith('categoria:'):
                category = hint.split(':', 1)[1]
                break

        # Discount depth labels
        for bucket in ('desconto_30', 'desconto_50', 'desconto_70'):
            if bucket in labels:
                desconto_buckets[bucket] += 1

        # Price mechanic labels
        if 'pix' in labels:
            pix_count += 1
        if 'parcelado_sem_juros' in labels:
            parcelado_count += 1
        if 'cashback' in labels:
            cashback_count += 1
        if 'menor_preco' in labels:
            menor_preco_count += 1
        if 'frete_gratis' in labels:
            frete_gratis_count += 1

        # Coupon type
        coupon_tipo = row.cupom_tipo or ''
        if coupon_tipo and coupon_tipo in ALLOWED_COUPON_TYPES:
            cupom_por_tipo[coupon_tipo] += 1

        # Per marketplace breakdown
        if marketplace:
            if marketplace not in por_marketplace:
                por_marketplace[marketplace] = {
                    'desconto_30': 0, 'desconto_50': 0, 'desconto_70': 0,
                    'pix': 0, 'parcelado_sem_juros': 0, 'cashback': 0,
                }
            mp = por_marketplace[marketplace]
            for bucket in ('desconto_30', 'desconto_50', 'desconto_70'):
                if bucket in labels:
                    mp[bucket] += 1
            if 'pix' in labels:
                mp['pix'] += 1
            if 'parcelado_sem_juros' in labels:
                mp['parcelado_sem_juros'] += 1
            if 'cashback' in labels:
                mp['cashback'] += 1

        # Per category breakdown
        if category:
            if category not in por_categoria:
                por_categoria[category] = {
                    'desconto_30': 0, 'desconto_50': 0, 'desconto_70': 0,
                    'pix': 0, 'parcelado_sem_juros': 0, 'cashback': 0,
                }
            cat = por_categoria[category]
            for bucket in ('desconto_30', 'desconto_50', 'desconto_70'):
                if bucket in labels:
                    cat[bucket] += 1
            if 'pix' in labels:
                cat['pix'] += 1
            if 'parcelado_sem_juros' in labels:
                cat['parcelado_sem_juros'] += 1
            if 'cashback' in labels:
                cat['cashback'] += 1

    return {
        'desconto_30': desconto_buckets.get('desconto_30', 0),
        'desconto_50': desconto_buckets.get('desconto_50', 0),
        'desconto_70': desconto_buckets.get('desconto_70', 0),
        'pix': pix_count,
        'parcelado_sem_juros': parcelado_count,
        'cashback': cashback_count,
        'menor_preco': menor_preco_count,
        'frete_gratis': frete_gratis_count,
        'cupom_por_tipo': dict(cupom_por_tipo),
        'por_marketplace': por_marketplace,
        'por_categoria': por_categoria,
    }


def build_copy_e_formato(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P0-3: Copy and format patterns aggregation."""
    rows = list(messages)
    total = len(rows)
    if total == 0:
        return {
            'emoji_densidade_media': 0,
            'emojis_top': [],
            'tem_headline_pct': 0,
            'tem_cta_pct': 0,
            'cta_termos_top': [],
            'tipo_midia': {},
            'tamanho_mensagem_media': 0,
            'usa_caixa_alta_pct': 0,
            'usa_negrito_pct': 0,
            'engajamento_por_copy': [],
        }

    emoji_density_sum = Decimal('0')
    emoji_density_count = 0
    all_emojis = Counter()
    headline_count = 0
    cta_count = 0
    cta_termos_counts = Counter()
    media_type_counts = Counter()
    tamanho_sum = 0
    tamanho_count = 0
    caixa_alta_count = 0
    caixa_alta_total = 0
    negrito_count = 0
    negrito_total = 0

    for row in rows:
        # Emoji density
        if row.emoji_densidade is not None:
            emoji_density_sum += Decimal(str(row.emoji_densidade))
            emoji_density_count += 1
        if row.emojis_top:
            for emoji in row.emojis_top:
                all_emojis[emoji] += 1

        # Headline
        if row.tem_headline is True:
            headline_count += 1

        # CTA
        if row.tem_cta is True:
            cta_count += 1
        for term in (row.cta_termos or []):
            if term in CTA_TERMS_SET:
                cta_termos_counts[term] += 1

        # Media type
        media_type = row.tipo_midia if row.tipo_midia in ALLOWED_MEDIA_TYPES else 'texto'
        media_type_counts[media_type] += 1

        # Message size
        if row.tamanho_mensagem is not None:
            tamanho_sum += row.tamanho_mensagem
            tamanho_count += 1

        # Uppercase
        if row.usa_caixa_alta is not None:
            caixa_alta_total += 1
            if row.usa_caixa_alta:
                caixa_alta_count += 1

        # Bold
        if row.usa_negrito is not None:
            negrito_total += 1
            if row.usa_negrito:
                negrito_count += 1

    emoji_densidade_media = float(emoji_density_sum / emoji_density_count) if emoji_density_count else 0
    tamanho_mensagem_media = round(tamanho_sum / tamanho_count) if tamanho_count else 0

    return {
        'emoji_densidade_media': round(emoji_densidade_media, 2),
        'emojis_top': [{'emoji': e, 'count': c} for e, c in all_emojis.most_common(10)],
        'tem_headline_pct': round(headline_count / total, 2) if total else 0,
        'tem_cta_pct': round(cta_count / total, 2) if total else 0,
        'cta_termos_top': [{'termo': t, 'count': c} for t, c in cta_termos_counts.most_common(10)],
        'tipo_midia': dict(media_type_counts),
        'tamanho_mensagem_media': tamanho_mensagem_media,
        'usa_caixa_alta_pct': round(caixa_alta_count / caixa_alta_total, 2) if caixa_alta_total else 0,
        'usa_negrito_pct': round(negrito_count / negrito_total, 2) if negrito_total else 0,
        'engajamento_por_copy': [],  # populated when engagement data is available (P0-1)
    }


def build_sinais_engajamento(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P0-1: Engagement signals aggregation with graceful degradation.

    WhatsApp usually returns all fields as null. When another source provides any
    engagement signal, rank by an additive safe score instead of treating missing
    fields as zero for averages.
    """
    rows = list(messages)
    engagement_fields = ('reacoes', 'visualizacoes', 'encaminhamentos', 'comentarios', 'qtd_repostagens')
    boolean_engagement_fields = ('repostado', 'fixado')
    has_engagement = any(
        any(getattr(r, field) is not None for field in engagement_fields)
        or any(getattr(r, field) is not None for field in boolean_engagement_fields)
        for r in rows
    )
    if not has_engagement:
        return {
            'top_por_reacoes': [],
            'top_por_engajamento': [],
            'engajamento_medio_por_marketplace': {},
            'engajamento_medio_por_categoria': {},
            'nota': 'Sinais de engajamento indisponíveis para esta fonte (WhatsApp não expõe reações/views). Campos ficam null e são excluídos de médias/rankings.',
        }

    ranked = []
    for row in rows:
        if (
            not any(getattr(row, field) is not None for field in engagement_fields)
            and not any(getattr(row, field) is not None for field in boolean_engagement_fields)
        ):
            continue
        score = (row.reacoes or 0) + (row.comentarios or 0) + (row.encaminhamentos or 0)
        if row.visualizacoes is not None:
            score += round(row.visualizacoes / 100)
        if row.repostado:
            score += (row.qtd_repostagens or 1) * 10
        if row.fixado:
            score += 25
        ranked.append((row, score))
    ranked.sort(key=lambda x: x[1], reverse=True)

    top_por_engajamento = []
    for row, score in ranked[:10]:
        entry = {
            'marketplace': _sanitize_marketplace(row.parsed_marketplace),
            'score_engajamento': score,
        }
        for field in engagement_fields:
            value = getattr(row, field)
            if value is not None:
                entry[field] = value
        if row.repostado is not None:
            entry['repostado'] = row.repostado
        if row.qtd_repostagens is not None:
            entry['qtd_repostagens'] = row.qtd_repostagens
        if row.fixado is not None:
            entry['fixado'] = row.fixado
        top_por_engajamento.append(entry)

    top_por_reacoes = []
    for row in sorted([r for r in rows if r.reacoes is not None], key=lambda r: r.reacoes or 0, reverse=True)[:10]:
        top_por_reacoes.append({
            'marketplace': _sanitize_marketplace(row.parsed_marketplace),
            'reacoes': row.reacoes,
            **({'visualizacoes': row.visualizacoes} if row.visualizacoes is not None else {}),
            **({'repostado': True} if row.repostado else {}),
            **({'fixado': True} if row.fixado else {}),
        })

    mp_groups: dict[str, list[int]] = {}
    cat_groups: dict[str, list[int]] = {}
    for row, score in ranked:
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        mp_groups.setdefault(marketplace, []).append(score)
        category = _extract_category(row)
        if category:
            cat_groups.setdefault(category, []).append(score)

    return {
        'top_por_reacoes': top_por_reacoes,
        'top_por_engajamento': top_por_engajamento,
        'engajamento_medio_por_marketplace': {
            mp: round(sum(values) / len(values), 1) for mp, values in mp_groups.items()
        },
        'engajamento_medio_por_categoria': {
            cat: round(sum(values) / len(values), 1) for cat, values in cat_groups.items()
        },
        'nota': '',
    }


def build_marketplace_detalhado(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P1-5: Richer marketplace detection with unknown domains log."""
    rows = list(messages)
    marketplace_counts = Counter()
    unknown_domains = []
    program_counts = Counter()

    for row in rows:
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        marketplace_counts[marketplace] += 1
        if marketplace == 'desconhecido' and row.marketplace_dominio_desconhecido:
            unknown_domains.append(row.marketplace_dominio_desconhecido)
        program = row.programa_entrega or ''
        if program and program in ALLOWED_DELIVERY_PROGRAMS:
            program_counts[program] += 1

    return {
        'contagem': dict(marketplace_counts),
        'dominios_desconhecidos': list(dict.fromkeys(unknown_domains))[:20],
        'programa_entrega': dict(program_counts),
    }


def build_marcas_por_categoria(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P1-6: Brand ranking within categories."""
    rows = list(messages)
    cat_brand: dict[str, Counter] = {}

    for row in rows:
        category = ''
        for hint in (row.scraper_hints or []):
            if hint.startswith('categoria:'):
                category = hint.split(':', 1)[1]
                break
        marca = row.marca or ''
        if not marca:
            continue
        if not category:
            category = 'sem_categoria'
        if category not in cat_brand:
            cat_brand[category] = Counter()
        cat_brand[category][marca] += 1

    result = {}
    for cat, brands in sorted(cat_brand.items()):
        result[cat] = [{'marca': m, 'count': c} for m, c in brands.most_common(10)]
    return result


def build_cadencia_e_timing(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P1-4: Cadence, timing and coverage lag aggregation."""
    rows = list(messages)
    if not rows:
        return {
            'heatmap_horario_dia': [],
            'frequencia_por_grupo': [],
            'intervalo_medio_por_grupo': {},
            'lag_cobertura': {
                'amostras': 0,
                'descontos_bot_publicou_primeiro': 0,
                'concorrente_publicou_primeiro': 0,
                'empate': 0,
                'lag_medio_horas': None,
            },
            'sazonalidade': [],
        }

    heatmap: dict[tuple[int, int], int] = {}
    for hour in range(24):
        for day in range(7):
            heatmap[(hour, day)] = 0

    for row in rows:
        if row.sent_at:
            local_dt = row.sent_at.astimezone(LOCAL_TZ)
            heatmap[(local_dt.hour, local_dt.weekday())] += 1

    heatmap_list = [
        {'hora': hour, 'dia_semana': day, 'count': count}
        for (hour, day), count in sorted(heatmap.items())
    ]

    group_freq: dict[str, list] = {}
    for row in rows:
        group_name = _sanitize_public_text(row.group.name, max_length=80)
        group_freq.setdefault(group_name, [])
        if row.sent_at:
            group_freq[group_name].append(row.sent_at)

    frequencia_por_grupo = []
    intervalo_medio_por_grupo = {}
    for group_name, timestamps in group_freq.items():
        posts = len(timestamps)
        if posts > 1:
            sorted_ts = sorted(timestamps)
            first_day = sorted_ts[0].astimezone(LOCAL_TZ).date()
            last_day = sorted_ts[-1].astimezone(LOCAL_TZ).date()
            days_span = max(1, (last_day - first_day).days + 1)
            posts_per_day = round(posts / days_span, 1)
            intervals = [
                (sorted_ts[i] - sorted_ts[i - 1]).total_seconds() / 3600
                for i in range(1, len(sorted_ts))
            ]
            avg_interval = round(sum(intervals) / len(intervals), 1) if intervals else None
        else:
            posts_per_day = posts
            avg_interval = None

        frequencia_por_grupo.append({
            'grupo': group_name,
            'posts': posts,
            'posts_por_dia': posts_per_day,
        })
        if avg_interval is not None:
            intervalo_medio_por_grupo[group_name] = avg_interval

    lag_summary = {
        'amostras': 0,
        'descontos_bot_publicou_primeiro': 0,
        'concorrente_publicou_primeiro': 0,
        'empate': 0,
        'lag_medio_horas': None,
    }
    try:
        offer_index = _build_offer_index()
        lags = []
        for row in rows:
            offer, _ = _match_own_offer(row, offer_index)
            lag = _coverage_lag_hours(row, offer)
            if lag is None:
                continue
            lag_summary['amostras'] += 1
            lags.append(lag)
            if lag < 0:
                lag_summary['descontos_bot_publicou_primeiro'] += 1
            elif lag > 0:
                lag_summary['concorrente_publicou_primeiro'] += 1
            else:
                lag_summary['empate'] += 1
        if lags:
            lag_summary['lag_medio_horas'] = round(sum(lags) / len(lags), 1)
    except Exception:
        pass

    return {
        'heatmap_horario_dia': heatmap_list,
        'frequencia_por_grupo': sorted(frequencia_por_grupo, key=lambda item: item['posts'], reverse=True),
        'intervalo_medio_por_grupo': intervalo_medio_por_grupo,
        'lag_cobertura': lag_summary,
        'sazonalidade': _detect_sazonalidade(rows),
    }


def build_cobertura(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P1-7: Coverage gap analysis.

    Cross-references competitor messages with our Offer table by normalized URL
    first, then by normalized title/text. The public payload never exposes raw
    competitor URLs or copy; backlog entries use aggregated combos and hashes.
    """
    rows = list(messages)
    try:
        offer_index = _build_offer_index()
    except Exception:
        return {
            'ofertas_nao_cobertas': 0,
            'taxa_sobreposicao': 0,
            'exclusivas_concorrente': 0,
            'tempo_ate_cobertura_horas_medio': None,
            'backlog_curadoria': [],
            'nota': 'Modelo Offer indisponível; análise de cobertura desabilitada.',
        }

    total = len(rows)
    if total == 0:
        return {
            'ofertas_nao_cobertas': 0,
            'taxa_sobreposicao': 0,
            'exclusivas_concorrente': 0,
            'tempo_ate_cobertura_horas_medio': None,
            'backlog_curadoria': [],
        }

    overlap_count = 0
    not_covered = []
    lag_values = []
    match_method_counts = Counter()

    for row in rows:
        offer, match_method = _match_own_offer(row, offer_index)
        if offer:
            overlap_count += 1
            match_method_counts[match_method] += 1
            lag = _coverage_lag_hours(row, offer)
            if lag is not None:
                lag_values.append(lag)
            continue

        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        category = _extract_category(row)
        not_covered.append({
            'marketplace': marketplace,
            'preco': _decimal_to_str(row.parsed_price),
            'categoria': category,
        })

    taxa_sobreposicao = round(overlap_count / total, 2) if total else 0
    exclusivas_concorrente = total - overlap_count
    backlog_counter = Counter()
    for item in not_covered:
        key = f"{item['marketplace']}:{item['categoria']}" if item['categoria'] else item['marketplace']
        backlog_counter[key] += 1

    backlog_curadoria = [
        {'comb': k, 'count': c}
        for k, c in backlog_counter.most_common(10)
    ]

    return {
        'ofertas_nao_cobertas': exclusivas_concorrente,
        'taxa_sobreposicao': taxa_sobreposicao,
        'exclusivas_concorrente': exclusivas_concorrente,
        'tempo_ate_cobertura_horas_medio': round(sum(lag_values) / len(lag_values), 1) if lag_values else None,
        'metodo_match': dict(match_method_counts),
        'backlog_curadoria': backlog_curadoria,
    }


def build_intelligent_insights(report: MarketIntelDailyReport, messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """Turn observer counters into a concise executive/action readout.

    No LLM and no raw third-party copy/URLs: this block is safe for the public
    JSON and for the no-agent cron notification.
    """
    rows = list(messages)
    total = len(rows)
    previous_total = ObservedWhatsAppMessage.objects.filter(
        sent_at__gte=report.window_start - timedelta(days=1),
        sent_at__lte=report.window_end - timedelta(days=1),
    ).count()

    if not total:
        return {
            'status': 'sem_dados',
            'resumo_executivo': 'Nenhuma mensagem observada no ciclo. O problema mais provável é coleta/webhook/buffer, não inteligência de mercado.',
            'variacao_vs_dia_anterior_pct': -100 if previous_total else 0,
            'alertas': [{
                'severidade': 'critico',
                'titulo': 'Observer sem dados no ciclo',
                'detalhe': 'Validar adapter Evolution/wa_service, allowlist de grupos, buffer e cron antes de interpretar tendências.',
            }],
            'oportunidades_prioritarias': [],
            'janelas_recomendadas': [],
            'acoes_recomendadas': [
                'Executar coleta manual e confirmar created/updated maior que zero.',
                'Validar /observer/groups e /observer/collect no provider ativo.',
                'Verificar se site/market-intel.json foi commitado e publicado após a geração.',
            ],
        }

    summary = summarize_messages(rows)
    coverage = build_cobertura(messages)
    copy = build_copy_e_formato(messages)
    mecanica = build_mecanica_preco(messages)
    timing = build_cadencia_e_timing(messages)

    top_marketplace = (summary.get('top_marketplaces') or [{}])[0]
    top_labels = summary.get('top_labels') or []
    marketplace_counts = {item['marketplace']: item['count'] for item in summary.get('top_marketplaces', [])}
    unknown_count = marketplace_counts.get('desconhecido', 0)
    unknown_pct = round(unknown_count / total, 2) if total else 0
    coupon_pct = round(summary.get('coupon_messages', 0) / total, 2)
    image_pct = round(summary.get('image_messages', 0) / total, 2)
    overlap = coverage.get('taxa_sobreposicao', 0) or 0
    backlog = coverage.get('backlog_curadoria') or []

    if previous_total:
        variation = round(((total - previous_total) / previous_total) * 100, 1)
    else:
        variation = 100 if total else 0

    heatmap = timing.get('heatmap_horario_dia') or []
    peak_slots = sorted(heatmap, key=lambda item: item.get('count', 0), reverse=True)[:3]
    weekday_names = ['seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'dom']
    windows = [
        {
            'dia_semana': weekday_names[slot['dia_semana']],
            'hora': slot['hora'],
            'count': slot['count'],
            'recomendacao': f"Testar publicação/curadoria perto de {slot['hora']:02d}h em {weekday_names[slot['dia_semana']]}",
        }
        for slot in peak_slots
        if slot.get('count', 0) > 0
    ]

    alerts = []
    if unknown_pct >= 0.15:
        alerts.append({
            'severidade': 'alto',
            'titulo': 'Muitos marketplaces desconhecidos',
            'detalhe': f'{unknown_count}/{total} mensagens ({unknown_pct:.0%}) não tiveram marketplace identificado; isso reduz a qualidade das recomendações.',
        })
    if overlap < 0.2:
        alerts.append({
            'severidade': 'medio',
            'titulo': 'Baixa sobreposição com o catálogo próprio',
            'detalhe': f'Taxa de cobertura {overlap:.0%}; priorizar lacunas recorrentes antes de aumentar volume de disparos.',
        })
    if variation <= -50:
        alerts.append({
            'severidade': 'alto',
            'titulo': 'Queda forte de volume observado',
            'detalhe': f'Volume caiu {abs(variation):.1f}% contra o dia anterior; checar coleta antes de concluir mudança de mercado.',
        })

    opportunities = []
    if backlog:
        top_gap = backlog[0]
        opportunities.append({
            'prioridade': 1,
            'tema': 'cobertura_de_catalogo',
            'sinal': top_gap['comb'],
            'impacto': top_gap['count'],
            'acao': 'Criar/ajustar scraper ou regra de curadoria para a lacuna mais recorrente.',
        })
    if coupon_pct >= 0.35:
        opportunities.append({
            'prioridade': 2,
            'tema': 'copy_e_oferta',
            'sinal': 'cupom_recorrente',
            'impacto': summary.get('coupon_messages', 0),
            'acao': 'Dar peso maior para ofertas com cupom explícito e destacar o cupom no criativo.',
        })
    if image_pct >= 0.5:
        opportunities.append({
            'prioridade': 3,
            'tema': 'criativo',
            'sinal': 'imagem_forte',
            'impacto': summary.get('image_messages', 0),
            'acao': 'Priorizar cards/imagens nativas e evitar ofertas sem mídia quando houver concorrência visual forte.',
        })
    if mecanica.get('pix', 0) or mecanica.get('parcelado_sem_juros', 0):
        opportunities.append({
            'prioridade': 4,
            'tema': 'mecanica_de_preco',
            'sinal': 'pix_ou_parcelamento',
            'impacto': mecanica.get('pix', 0) + mecanica.get('parcelado_sem_juros', 0),
            'acao': 'Exibir Pix/parcelamento como metadado de ranking, não só dentro do texto.',
        })

    top_label_text = ', '.join(f"{item['label']} ({item['count']})" for item in top_labels[:3]) or 'sem labels dominantes'
    resumo = (
        f"{total} mensagens no ciclo ({variation:+.1f}% vs dia anterior). "
        f"Marketplace líder: {top_marketplace.get('marketplace', 'n/d')} ({top_marketplace.get('count', 0)} menções). "
        f"Sinais dominantes: {top_label_text}. Cobertura própria estimada: {overlap:.0%}."
    )

    actions = [item['acao'] for item in opportunities[:4]] or ['Manter coleta diária e acumular mais dados antes de mudar estratégia.']
    return {
        'status': 'ok',
        'resumo_executivo': resumo,
        'variacao_vs_dia_anterior_pct': variation,
        'alertas': alerts,
        'oportunidades_prioritarias': opportunities,
        'janelas_recomendadas': windows,
        'metricas_chave': {
            'mensagens': total,
            'marketplace_lider': top_marketplace,
            'cupom_pct': coupon_pct,
            'imagem_pct': image_pct,
            'marketplace_desconhecido_pct': unknown_pct,
            'taxa_sobreposicao': overlap,
            'tem_cta_pct': copy.get('tem_cta_pct', 0),
        },
        'acoes_recomendadas': actions,
    }


def build_daily_report_payload(report: MarketIntelDailyReport) -> dict:
    all_messages = ObservedWhatsAppMessage.objects.select_related('group').all()
    cycle_messages = all_messages.filter(sent_at__gte=report.window_start, sent_at__lte=report.window_end)
    cumulative_summary = summarize_messages(all_messages)
    cycle_summary = summarize_messages(cycle_messages)
    return {
        'version': '2.0',
        'report_type': 'incremental_market_intel',
        'generated_at': timezone.now().isoformat(),
        'date': report.date.isoformat(),
        'window': {
            'start': report.window_start.isoformat(),
            'end': report.window_end.isoformat(),
        },
        # v1 blocks (unchanged)
        'summary': cumulative_summary,
        'cycle_summary': cycle_summary,
        'recommendations': build_recommendations(cumulative_summary),
        'cycle_recommendations': build_recommendations(cycle_summary),
        'scraper_opportunities': build_scraper_opportunities(all_messages),
        'cycle_scraper_opportunities': build_scraper_opportunities(cycle_messages),
        'analyzed_offers': build_analyzed_offers(all_messages),
        # v2 new blocks
        'mecanica_preco': build_mecanica_preco(cycle_messages),
        'mecanica_preco_acumulada': build_mecanica_preco(all_messages),
        'copy_e_formato': build_copy_e_formato(cycle_messages),
        'copy_e_formato_acumulada': build_copy_e_formato(all_messages),
        'sinais_engajamento': build_sinais_engajamento(cycle_messages),
        'sinais_engajamento_acumulado': build_sinais_engajamento(all_messages),
        'marketplace_detalhado': build_marketplace_detalhado(cycle_messages),
        'marketplace_detalhado_acumulado': build_marketplace_detalhado(all_messages),
        'marcas_por_categoria': build_marcas_por_categoria(cycle_messages),
        'marcas_por_categoria_acumulada': build_marcas_por_categoria(all_messages),
        'cadencia_e_timing': build_cadencia_e_timing(cycle_messages),
        'cadencia_e_timing_acumulada': build_cadencia_e_timing(all_messages),
        'cobertura': build_cobertura(cycle_messages),
        'cobertura_acumulada': build_cobertura(all_messages),
        'insights_inteligentes': build_intelligent_insights(report, cycle_messages),
        'privacy': {
            'sender_identity': 'sha256 hash only in database; omitted from report',
            'message_identity': 'Source message identifiers omitted from report',
            'group_identity': 'WhatsApp group JIDs omitted from report; group names are kept for operational analysis',
            'observed_urls': 'omitted from report; never publish third-party affiliate links',
            'raw_text': 'raw third-party copy omitted from report',
        },
    }


def build_analyzed_offers(messages: QuerySet[ObservedWhatsAppMessage]) -> list[dict]:
    rows = list(messages.order_by('-sent_at', '-id'))
    return [
        {
            'observed_at': row.sent_at.isoformat(),
            'group': _sanitize_public_text(row.group.name),
            'marketplace': _sanitize_marketplace(row.parsed_marketplace),
            'price': _decimal_to_str(row.parsed_price),
            'original_price': _decimal_to_str(row.parsed_original_price),
            'discount_pct': _decimal_to_str(row.parsed_discount_pct),
            'coupon': _sanitize_coupon(row.parsed_coupon),
            'has_coupon': bool(_sanitize_coupon(row.parsed_coupon)),
            'has_image': row.has_image,
            'raw_type': row.raw_type if row.raw_type in ALLOWED_RAW_TYPES else '',
            'labels': _allowed_values(row.editorial_labels or [], ALL_LABELS),
            'scraper_hints': _allowed_values(row.scraper_hints or [], ALLOWED_HINTS),
            # v2 fields
            'parcelamento': row.parcelamento,
            'parcelado_sem_juros': row.parcelado_sem_juros,
            'pix': row.pix,
            'pix_desconto_pct': _decimal_to_str(row.pix_desconto_pct) if row.pix_desconto_pct else '',
            'cashback': row.cashback,
            'menor_preco': row.menor_preco,
            'cupom_tipo': row.cupom_tipo if row.cupom_tipo in ALLOWED_COUPON_TYPES else '',
            'tipo_midia': row.tipo_midia if row.tipo_midia in ALLOWED_MEDIA_TYPES else '',
            'marca': row.marca or '',
            'programa_entrega': row.programa_entrega if row.programa_entrega in ALLOWED_DELIVERY_PROGRAMS else '',
        }
        for row in rows
    ]


def _counter_items(counter: Counter, key: str) -> list[dict]:
    return [{key: name, 'count': count} for name, count in counter.most_common(10)]


def _allowed_values(values: list, allowed: set[str]) -> list[str]:
    sanitized = []
    for value in values:
        text = str(value).strip()
        if text in allowed and text not in sanitized:
            sanitized.append(text)
    return sanitized


def _sanitize_coupon(value: str) -> str:
    coupon = str(value or '').strip().upper()
    return coupon if COUPON_RE.fullmatch(coupon) else ''


def _sanitize_marketplace(value: str) -> str:
    marketplace = str(value or '').strip().lower()
    return marketplace if marketplace in ALLOWED_MARKETPLACES else 'desconhecido'


def _sanitize_public_text(value: str, max_length: int = 120) -> str:
    text = str(value or '').strip()
    text = URL_OR_WHATSAPP_ID_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length]


def _decimal_to_str(value: Decimal | None) -> str:
    return str(value) if value is not None else ''