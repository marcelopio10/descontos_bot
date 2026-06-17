import re
from collections import Counter
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal
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
    """P0-1: Engagement signals aggregation (mostly null for WhatsApp)."""
    rows = list(messages)
    has_engagement = any(r.reacoes is not None for r in rows)
    if not has_engagement:
        return {
            'top_por_reacoes': [],
            'engajamento_medio_por_marketplace': {},
            'engajamento_medio_por_categoria': {},
            'nota': 'Sinais de engajamento indisponíveis para esta fonte (WhatsApp não expõe reações/views). Ative grupos Telegram para dados de engajamento.',
        }

    # Build ranking by reacoes
    with_reacoes = [(r, r.reacoes or 0) for r in rows if r.reacoes is not None]
    with_reacoes.sort(key=lambda x: x[1], reverse=True)
    top_por_reacoes = []
    for row, reacoes in with_reacoes[:10]:
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        entry = {
            'marketplace': marketplace,
            'reacoes': reacoes,
        }
        if row.visualizacoes is not None:
            entry['visualizacoes'] = row.visualizacoes
        if row.repostado:
            entry['repostado'] = True
        if row.fixado:
            entry['fixado'] = True
        top_por_reacoes.append(entry)

    # Per marketplace averages
    mp_groups: dict[str, list] = {}
    for row in rows:
        if row.reacoes is None:
            continue
        marketplace = _sanitize_marketplace(row.parsed_marketplace)
        if marketplace not in mp_groups:
            mp_groups[marketplace] = []
        mp_groups[marketplace].append(row.reacoes)

    engajamento_por_marketplace = {}
    for mp, values in mp_groups.items():
        avg = sum(values) / len(values)
        engajamento_por_marketplace[mp] = round(avg, 1)

    # Per category averages
    cat_groups: dict[str, list] = {}
    for row in rows:
        if row.reacoes is None:
            continue
        category = ''
        for hint in (row.scraper_hints or []):
            if hint.startswith('categoria:'):
                category = hint.split(':', 1)[1]
                break
        if not category:
            continue
        if category not in cat_groups:
            cat_groups[category] = []
        cat_groups[category].append(row.reacoes)

    engajamento_por_categoria = {}
    for cat, values in cat_groups.items():
        avg = sum(values) / len(values)
        engajamento_por_categoria[cat] = round(avg, 1)

    return {
        'top_por_reacoes': top_por_reacoes,
        'engajamento_medio_por_marketplace': engajamento_por_marketplace,
        'engajamento_medio_por_categoria': engajamento_por_categoria,
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
    """P1-4: Cadence and timing aggregation."""
    rows = list(messages)
    if not rows:
        return {
            'heatmap_horario_dia': [],
            'frequencia_por_grupo': [],
            'intervalo_medio_por_grupo': {},
        }

    # Heatmap: hour (0-23) × day_of_week (0=mon...6=sun)
    heatmap: dict[tuple[int, int], int] = {}
    for hour in range(24):
        for day in range(7):
            heatmap[(hour, day)] = 0

    for row in rows:
        if row.sent_at:
            local_dt = row.sent_at.astimezone(LOCAL_TZ)
            # Python: weekday() 0=Monday, 6=Sunday
            heatmap[(local_dt.hour, local_dt.weekday())] += 1

    heatmap_list = [
        {'hora': hour, 'dia_semana': day, 'count': count}
        for (hour, day), count in sorted(heatmap.items())
    ]

    # Frequency per group
    group_freq: dict[str, list] = {}
    for row in rows:
        group_name = _sanitize_public_text(row.group.name, max_length=80)
        if group_name not in group_freq:
            group_freq[group_name] = []
        if row.sent_at:
            group_freq[group_name].append(row.sent_at)

    frequencia_por_grupo = []
    intervalo_medio_por_grupo = {}
    for group_name, timestamps in group_freq.items():
        posts = len(timestamps)
        # Calculate days span
        if posts > 1:
            sorted_ts = sorted(timestamps)
            days_span = max(1, (sorted_ts[-1] - sorted_ts[0]).total_seconds() / 86400)
            posts_per_day = round(posts / days_span, 1)
            # Average interval in hours
            intervals = []
            for i in range(1, len(sorted_ts)):
                delta = (sorted_ts[i] - sorted_ts[i-1]).total_seconds() / 3600
                intervals.append(delta)
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

    return {
        'heatmap_horario_dia': heatmap_list,
        'frequencia_por_grupo': frequencia_por_grupo,
        'intervalo_medio_por_grupo': intervalo_medio_por_grupo,
    }


def build_cobertura(messages: QuerySet[ObservedWhatsAppMessage]) -> dict:
    """P1-7: Coverage gap analysis — cross-references with Offer model."""
    rows = list(messages)
    try:
        from apps.offers.models import Offer
        own_urls = set(
            Offer.objects.filter(is_active=True)
            .values_list('product_url', flat=True)
        )
    except Exception:
        # If Offer model is unavailable, return empty coverage
        return {
            'ofertas_nao_cobertas': 0,
            'taxa_sobreposicao': 0,
            'exclusivas_concorrente': 0,
            'backlog_curadoria': [],
            'nota': 'Modelo Offer indisponível; análise de cobertura desabilitada.',
        }

    total = len(rows)
    if total == 0:
        return {
            'ofertas_nao_cobertas': 0,
            'taxa_sobreposicao': 0,
            'exclusivas_concorrente': 0,
            'backlog_curadoria': [],
        }

    # Match by URL presence (normalized domain+path)
    def _normalize_url(url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f'{parsed.netloc}{parsed.path}'.rstrip('/').lower()

    own_urls_norm = {_normalize_url(u) for u in own_urls if u}

    overlap_count = 0
    not_covered = []
    for row in rows:
        row_urls = row.urls or []
        matched = False
        for url in row_urls:
            if _normalize_url(url) in own_urls_norm:
                matched = True
                break
        if matched:
            overlap_count += 1
        else:
            marketplace = _sanitize_marketplace(row.parsed_marketplace)
            not_covered.append({
                'marketplace': marketplace,
                'preco': _decimal_to_str(row.parsed_price),
                'categoria': next(
                    (h.split(':', 1)[1] for h in (row.scraper_hints or []) if h.startswith('categoria:')),
                    '',
                ),
            })

    taxa_sobreposicao = round(overlap_count / total, 2) if total else 0
    exclusivas_concorrente = total - overlap_count

    # Priority backlog: marketplace + category combos
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
        'backlog_curadoria': backlog_curadoria,
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
        'marketplace_detalhado': build_marketplace_detalhado(cycle_messages),
        'marcas_por_categoria': build_marcas_por_categoria(cycle_messages),
        'cadencia_e_timing': build_cadencia_e_timing(cycle_messages),
        'cobertura': build_cobertura(cycle_messages),
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