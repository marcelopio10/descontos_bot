"""Agregações operacionais mínimas para o painel do dono do bot (Tarefa 2.1).

Todas as funções aqui são somente-leitura (nenhuma escrita no banco) e usam o
ORM do Django (`values().annotate()`), sem SQL cru. O objetivo é responder,
de forma rápida e observável, quatro perguntas:

1. Quantos envios por dia/canal estão saindo? (`deliveries_per_day_by_channel`)
2. Quantas ofertas coletadas/válidas por marketplace, e quantos runs de
   scraping falharam? (`scraping_summary`)
3. Quantos runs de curadoria falharam? (`curation_summary`)
4. Há quanto tempo o observer (market intel) não coleta nada?
   (`observer_last_collection`)

`build_operational_panel()` combina as quatro em um único snapshot, usado
pelo comando `painel_operacional`.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.curation.models import CurationRun
from apps.distribution.models import Delivery
from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppMessage
from apps.scraping.models import ScrapingRun


DEFAULT_DAYS = 7
OBSERVER_STALE_HOURS = 24


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


def build_operational_panel(days: int = DEFAULT_DAYS) -> OperationalPanel:
    return OperationalPanel(
        generated_at=timezone.now(),
        days=days,
        deliveries=deliveries_per_day_by_channel(days=days),
        scraping=scraping_summary(days=days),
        curation=curation_summary(days=days),
        observer=observer_last_collection(),
    )
