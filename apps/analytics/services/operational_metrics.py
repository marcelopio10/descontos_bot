"""Agregações operacionais mínimas para o painel do dono do bot (Tarefa 2.1).

Todas as funções aqui são somente-leitura (nenhuma escrita no banco) e usam o
ORM do Django (`values().annotate()`), sem SQL cru. O objetivo é responder,
de forma rápida e observável, cinco perguntas:

1. Quantos envios por dia/canal estão saindo? (`deliveries_per_day_by_channel`)
2. Quantas ofertas coletadas/válidas por marketplace, e quantos runs de
   scraping falharam? (`scraping_summary`)
3. Quantos runs de curadoria falharam? (`curation_summary`)
4. Há quanto tempo o observer (market intel) não coleta nada?
   (`observer_last_collection`)
5. Por marketplace e por semana, quantos envios saíram e quanta comissão foi
   reportada na mesma janela? (`deliveries_vs_commission_by_marketplace_week`
   — Tarefa 4.2. Para ML/Amazon isso é **correlação temporal**, não
   atribuição exata — RESTR-03: nenhum dos dois expõe clique por canal de
   forma confiável. Para Shopee já é atribuição real via subId, Tarefa 4.1.)
6. Como está crescendo cada canal (membros/seguidores) ao longo do tempo?
   (`channel_membership_series` — Tarefa 7.3, achado H9. Dado é entrada
   manual periódica, `MetricaCanalDiaria` — LGPD: só contagem agregada.)

`build_operational_panel()` combina as seis em um único snapshot, usado
pelo comando `painel_operacional`.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from apps.analytics.models import (
    AffiliateConversion,
    AffiliateSource,
    FonteMetricaCanal,
    MetricaCanalDiaria,
)
from apps.curation.models import CurationRun
from apps.distribution.models import Delivery
from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage
from apps.scraping.models import ScrapingRun


DEFAULT_DAYS = 7
DEFAULT_WEEKS = 8
OBSERVER_STALE_HOURS = 24
# Membros/seguidores são registrados por entrada manual periódica (não diária
# como os envios), então a janela padrão é mais larga para não mostrar uma
# curva vazia entre duas medições espaçadas.
DEFAULT_MEMBERSHIP_DAYS = 90


# --------------------------------------------------------------------------
# Envios por dia/canal
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelDayCount:
    day: date
    channel_code: str
    channel_name: str
    sent_count: int


@dataclass(frozen=True)
class DeliveriesReport:
    days: int
    since: datetime
    rows: list[ChannelDayCount] = field(default_factory=list)
    totals_by_channel: dict[str, int] = field(default_factory=dict)
    total_sent: int = 0


def deliveries_per_day_by_channel(days: int = DEFAULT_DAYS) -> DeliveriesReport:
    """Envios (`Delivery.delivery_status=sent`) por dia e por canal social."""
    now = timezone.now()
    since = now - timedelta(days=days)

    queryset = (
        Delivery.objects.filter(
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=since,
        )
        .annotate(day=TruncDate('sent_at'))
        .values('day', 'social_channel__code', 'social_channel__name')
        .annotate(sent_count=Count('id'))
        .order_by('-day', 'social_channel__code')
    )

    rows = [
        ChannelDayCount(
            day=row['day'],
            channel_code=row['social_channel__code'],
            channel_name=row['social_channel__name'],
            sent_count=row['sent_count'],
        )
        for row in queryset
    ]

    totals_by_channel: dict[str, int] = {}
    for row in rows:
        totals_by_channel[row.channel_code] = (
            totals_by_channel.get(row.channel_code, 0) + row.sent_count
        )

    return DeliveriesReport(
        days=days,
        since=since,
        rows=rows,
        totals_by_channel=totals_by_channel,
        total_sent=sum(totals_by_channel.values()),
    )


# --------------------------------------------------------------------------
# Scraping: coletado/válido por marketplace + runs por status
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketplaceScrapingStats:
    marketplace_code: str
    marketplace_name: str
    total_collected: int
    total_valid: int
    run_count: int


@dataclass(frozen=True)
class ScrapingSummaryReport:
    days: int
    since: datetime
    by_marketplace: list[MarketplaceScrapingStats] = field(default_factory=list)
    runs_by_status: dict[str, int] = field(default_factory=dict)
    total_runs: int = 0
    failed_runs: int = 0
    failed_rate_pct: float = 0.0


def scraping_summary(days: int = DEFAULT_DAYS) -> ScrapingSummaryReport:
    """Ofertas coletadas/válidas por marketplace + contagem de runs por status."""
    now = timezone.now()
    since = now - timedelta(days=days)

    queryset = ScrapingRun.objects.filter(started_at__gte=since)

    by_marketplace_rows = (
        queryset.values('marketplace__code', 'marketplace__name')
        .annotate(
            total_collected=Sum('total_collected'),
            total_valid=Sum('total_valid'),
            run_count=Count('id'),
        )
        .order_by('marketplace__code')
    )
    by_marketplace = [
        MarketplaceScrapingStats(
            marketplace_code=row['marketplace__code'] or 'sem_marketplace',
            marketplace_name=row['marketplace__name'] or 'Sem marketplace',
            total_collected=row['total_collected'] or 0,
            total_valid=row['total_valid'] or 0,
            run_count=row['run_count'],
        )
        for row in by_marketplace_rows
    ]

    runs_by_status = {
        row['status']: row['count']
        for row in queryset.values('status').annotate(count=Count('id'))
    }
    total_runs = sum(runs_by_status.values())
    failed_runs = runs_by_status.get(ScrapingRun.RunStatus.FAILED, 0)
    failed_rate_pct = round((failed_runs / total_runs) * 100, 1) if total_runs else 0.0

    return ScrapingSummaryReport(
        days=days,
        since=since,
        by_marketplace=by_marketplace,
        runs_by_status=runs_by_status,
        total_runs=total_runs,
        failed_runs=failed_runs,
        failed_rate_pct=failed_rate_pct,
    )


# --------------------------------------------------------------------------
# Curadoria: runs por status + taxa de FAILED
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CurationSummaryReport:
    days: int
    since: datetime
    runs_by_status: dict[str, int] = field(default_factory=dict)
    total_runs: int = 0
    failed_runs: int = 0
    failed_rate_pct: float = 0.0


def curation_summary(days: int = DEFAULT_DAYS) -> CurationSummaryReport:
    """Contagem de `CurationRun` por status e taxa de FAILED no período."""
    now = timezone.now()
    since = now - timedelta(days=days)

    queryset = CurationRun.objects.filter(created_at__gte=since)

    runs_by_status = {
        row['status']: row['count']
        for row in queryset.values('status').annotate(count=Count('id'))
    }
    total_runs = sum(runs_by_status.values())
    failed_runs = runs_by_status.get(CurationRun.Status.FAILED, 0)
    failed_rate_pct = round((failed_runs / total_runs) * 100, 1) if total_runs else 0.0

    return CurationSummaryReport(
        days=days,
        since=since,
        runs_by_status=runs_by_status,
        total_runs=total_runs,
        failed_runs=failed_runs,
        failed_rate_pct=failed_rate_pct,
    )


# --------------------------------------------------------------------------
# Observer (market intel): última coleta
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ObserverStatus:
    last_message_collected_at: datetime | None
    last_message_group_name: str | None
    last_daily_report_date: date | None
    hours_since_last_collection: float | None
    is_stale: bool


def observer_last_collection() -> ObserverStatus:
    """Timestamp da última mensagem observada pelo market intel e há quanto
    tempo isso foi. `is_stale=True` quando não há coleta há mais de
    `OBSERVER_STALE_HOURS` horas (ou nunca houve coleta)."""
    now = timezone.now()

    last_message = (
        ObservedWhatsAppMessage.objects.select_related('group')
        .order_by('-collected_at')
        .first()
    )
    last_report = MarketIntelDailyReport.objects.order_by('-date').first()

    last_collected_at = last_message.collected_at if last_message else None
    hours_since = None
    if last_collected_at is not None:
        hours_since = round((now - last_collected_at).total_seconds() / 3600, 1)

    is_stale = hours_since is None or hours_since > OBSERVER_STALE_HOURS

    return ObserverStatus(
        last_message_collected_at=last_collected_at,
        last_message_group_name=last_message.group.name if last_message else None,
        last_daily_report_date=last_report.date if last_report else None,
        hours_since_last_collection=hours_since,
        is_stale=is_stale,
    )


# --------------------------------------------------------------------------
# Correlação temporal envios x comissão, por marketplace/semana (Tarefa 4.2)
# --------------------------------------------------------------------------

# RESTR-03: Amazon e Mercado Livre não expõem clique por canal de forma
# confiável (click tracking próprio é best-effort/só Amazon — ver
# docs/LINK_POLICY.md). Por isso o cruzamento com esses dois marketplaces só
# pode ser rotulado como correlação temporal (mesma semana), nunca atribuição
# exata por envio.
CORRELATION_LABEL = 'correlação (ML/Amazon)'
# Shopee já carrega subId de canal nativo no link (Tarefa 4.1), então a
# comissão reportada por semana/canal é atribuição real, não só correlação.
ATTRIBUTION_LABEL = 'atribuição (Shopee, via subId)'

# `AffiliateSource` (fonte do relatório de comissão) não usa os mesmos
# códigos de `Marketplace.code` (ex.: `mercado_livre` vs `mercadolivre`) —
# este mapa faz a ponte para poder cruzar com `Delivery.offer__marketplace__code`.
_SOURCE_TO_MARKETPLACE_CODE = {
    AffiliateSource.AMAZON: 'amazon',
    AffiliateSource.MERCADO_LIVRE: 'mercadolivre',
    AffiliateSource.SHOPEE: 'shopee',
}


@dataclass(frozen=True)
class MarketplaceWeekCorrelation:
    week_start: date
    marketplace_code: str
    marketplace_name: str
    sent_count: int
    commission_brl: Decimal
    conversions: int
    label: str


@dataclass(frozen=True)
class DeliveryCommissionCorrelationReport:
    weeks: int
    since: datetime
    note: str
    rows: list[MarketplaceWeekCorrelation] = field(default_factory=list)


def deliveries_vs_commission_by_marketplace_week(
    weeks: int = DEFAULT_WEEKS,
) -> DeliveryCommissionCorrelationReport:
    """Cruza envios (`Delivery`) com comissão (`AffiliateConversion`), por
    marketplace e por semana (ISO, início na segunda-feira).

    Para Amazon e Mercado Livre isso é **correlação temporal** (quantos
    envios saíram e quanta comissão o marketplace reportou na mesma semana),
    **não atribuição exata** por envio — RESTR-03, nenhum dos dois expõe
    clique por canal de forma confiável. Para Shopee, a comissão já vem
    atribuída por canal via subId (Tarefa 4.1), então é rotulada como
    atribuição real, não correlação.

    Somente leitura — `values().annotate()`, sem SQL cru, mesmo estilo do
    resto do módulo.
    """
    now = timezone.now()
    since = now - timedelta(weeks=weeks)
    since_date = since.date()

    sent_by_week_marketplace: dict[tuple[date, str], dict] = {}
    deliveries_queryset = (
        Delivery.objects.filter(
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=since,
        )
        .annotate(week=TruncWeek('sent_at'))
        .values('week', 'offer__marketplace__code', 'offer__marketplace__name')
        .annotate(sent_count=Count('id'))
    )
    for row in deliveries_queryset:
        week = row['week']
        week_date = week.date() if hasattr(week, 'date') else week
        marketplace_code = row['offer__marketplace__code'] or 'sem_marketplace'
        sent_by_week_marketplace[(week_date, marketplace_code)] = {
            'sent_count': row['sent_count'],
            'marketplace_name': row['offer__marketplace__name'] or 'Sem marketplace',
        }

    # Usa `period_end` (não `period_start`) para filtrar e para o bucket semanal.
    # Relatórios manuais de ML/Amazon (RESTR-04) cobrem períodos longos (ex.: um
    # mês inteiro) — um relatório cujo `period_start` é anterior à janela de
    # lookback mas que ainda está em vigor (period_end dentro da janela) não pode
    # ser descartado, senão a comissão real desaparece silenciosamente do painel
    # (achado real: 10 conversões ML reais, period_start=2026-05-03/period_end=
    # 2026-06-02, ficavam de fora com `period_start__gte=since_date`). Atribuir
    # a comissão à semana de `period_end` (fechamento/reporte) evita fabricar uma
    # distribuição diária/semanal que os dados não sustentam.
    commission_by_week_marketplace: dict[tuple[date, str], dict] = {}
    commission_queryset = (
        AffiliateConversion.objects.filter(
            source__in=list(_SOURCE_TO_MARKETPLACE_CODE),
            period_end__gte=since_date,
        )
        .annotate(week=TruncWeek('period_end'))
        .values('week', 'source')
        .annotate(commission_brl=Sum('commission_brl'), conversions=Sum('conversions'))
    )
    for row in commission_queryset:
        marketplace_code = _SOURCE_TO_MARKETPLACE_CODE.get(row['source'])
        if not marketplace_code:
            continue
        key = (row['week'], marketplace_code)
        bucket = commission_by_week_marketplace.setdefault(
            key, {'commission_brl': Decimal('0'), 'conversions': 0},
        )
        bucket['commission_brl'] += row['commission_brl'] or Decimal('0')
        bucket['conversions'] += row['conversions'] or 0

    all_keys = set(sent_by_week_marketplace) | set(commission_by_week_marketplace)
    rows = []
    for week_date, marketplace_code in sorted(all_keys, key=lambda kv: (kv[0], kv[1])):
        sent_info = sent_by_week_marketplace.get((week_date, marketplace_code), {})
        commission_info = commission_by_week_marketplace.get((week_date, marketplace_code), {})
        label = ATTRIBUTION_LABEL if marketplace_code == 'shopee' else CORRELATION_LABEL
        rows.append(
            MarketplaceWeekCorrelation(
                week_start=week_date,
                marketplace_code=marketplace_code,
                marketplace_name=sent_info.get('marketplace_name', marketplace_code),
                sent_count=sent_info.get('sent_count', 0),
                commission_brl=commission_info.get('commission_brl', Decimal('0')),
                conversions=commission_info.get('conversions', 0),
                label=label,
            )
        )

    return DeliveryCommissionCorrelationReport(
        weeks=weeks,
        since=since,
        note=(
            'Para Mercado Livre e Amazon (RESTR-03), envios x comissão na '
            'mesma semana é correlação temporal, não atribuição exata por '
            'clique/envio. Para Shopee, a comissão já é atribuída por canal '
            'via subId (Tarefa 4.1).'
        ),
        rows=rows,
    )


# --------------------------------------------------------------------------
# Crescimento: membros/seguidores por canal (Tarefa 7.3, achado H9)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelMembershipPoint:
    data: date
    membros: int
    posts_publicados: int
    cliques_estimados: int | None


@dataclass(frozen=True)
class ChannelMembershipSeries:
    channel_code: str
    channel_name: str
    points: list[ChannelMembershipPoint] = field(default_factory=list)


@dataclass(frozen=True)
class MembershipGrowthReport:
    days: int
    since: date
    series: list[ChannelMembershipSeries] = field(default_factory=list)
    unverified_points: int = 0


def channel_membership_series(days: int = DEFAULT_MEMBERSHIP_DAYS) -> MembershipGrowthReport:
    """Série temporal de membros/seguidores por canal, a partir de
    `MetricaCanalDiaria` (entrada manual periódica — LGPD: só contagem
    agregada, nunca dado individual de terceiro).

    Quando `posts_publicados` não foi preenchido manualmente na medição, esta
    função completa o ponto com a contagem real de envios (`Delivery`
    sent) do canal naquele dia — mesma fonte de `deliveries_per_day_by_channel`
    — em vez de forçar uma segunda entrada manual redundante.

    **Pontos com `fonte='estimado'` ficam fora da curva** (2026-08-23): os três
    registros que existiam eram estimativas erradas por 12× e 143×, e curva
    traçada sobre palpite é pior que curva vazia, porque induz decisão. O total
    descartado vai em `unverified_points`, para o descarte ser visível.
    """
    since_date = timezone.now().date() - timedelta(days=days)

    sent_by_channel_day = {
        (row.channel_code, row.day): row.sent_count
        for row in deliveries_per_day_by_channel(days=days).rows
    }

    na_janela = MetricaCanalDiaria.objects.filter(data__gte=since_date)
    unverified_points = na_janela.filter(fonte=FonteMetricaCanal.ESTIMADO).count()
    queryset = (
        na_janela.exclude(fonte=FonteMetricaCanal.ESTIMADO)
        .select_related('canal')
        .order_by('canal__code', 'data')
    )

    points_by_channel: dict[str, list[ChannelMembershipPoint]] = {}
    channel_names: dict[str, str] = {}
    for row in queryset:
        posts_publicados = row.posts_publicados
        if posts_publicados is None:
            posts_publicados = sent_by_channel_day.get((row.canal.code, row.data), 0)

        points_by_channel.setdefault(row.canal.code, []).append(
            ChannelMembershipPoint(
                data=row.data,
                membros=row.membros,
                posts_publicados=posts_publicados,
                cliques_estimados=row.cliques_estimados,
            )
        )
        channel_names[row.canal.code] = row.canal.name

    series = [
        ChannelMembershipSeries(
            channel_code=code,
            channel_name=channel_names[code],
            points=points,
        )
        for code, points in sorted(points_by_channel.items())
    ]

    return MembershipGrowthReport(
        days=days,
        since=since_date,
        series=series,
        unverified_points=unverified_points,
    )


# --------------------------------------------------------------------------
# Painel combinado
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OperationalPanel:
    generated_at: datetime
    days: int
    deliveries: DeliveriesReport
    scraping: ScrapingSummaryReport
    curation: CurationSummaryReport
    observer: ObserverStatus
    commission_correlation: DeliveryCommissionCorrelationReport
    membership: MembershipGrowthReport


def build_operational_panel(
    days: int = DEFAULT_DAYS,
    weeks: int = DEFAULT_WEEKS,
    membership_days: int = DEFAULT_MEMBERSHIP_DAYS,
) -> OperationalPanel:
    return OperationalPanel(
        generated_at=timezone.now(),
        days=days,
        deliveries=deliveries_per_day_by_channel(days=days),
        scraping=scraping_summary(days=days),
        curation=curation_summary(days=days),
        observer=observer_last_collection(),
        commission_correlation=deliveries_vs_commission_by_marketplace_week(weeks=weeks),
        membership=channel_membership_series(days=membership_days),
    )
