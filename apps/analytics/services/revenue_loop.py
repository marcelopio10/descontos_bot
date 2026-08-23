"""Relatório semanal: o que publicamos × o que vendeu.

Item 7 da Onda 1 do diagnóstico v2. O laço que faltou por 2,5 meses: sem cruzar
publicação com venda, o corte da faixa de R$ 500 levou 82 dias para aparecer.
Este relatório existe para que a próxima quebra apareça em uma semana.

Três recortes, nesta ordem de confiabilidade:

1. **Por faixa de preço** — o recorte que teria pego a quebra. Usa
   `saleValue` do painel de um lado e o preço publicado do outro, ambos
   sempre presentes.
2. **Por categoria** — depende do casamento venda↔oferta, que resolve ~58%
   das vendas. A cobertura é reportada junto; ler o resto como amostra.
3. **Por caminho de publicação** (curadoria IA × selector legado) — instrumenta
   a decisão do item 9. Mede envio, não qualidade: o que ele mostra é quanto
   de receita passa por um caminho que roda sem supervisão.

Limites que o relatório carrega explicitamente, em vez de esconder:

- **Só Mercado Livre.** É o único marketplace com venda a venda
  (`MLAffiliateSale`). Amazon e Shopee ficam de fora dos cruzamentos — incluí-los
  na publicação e não na venda produziria um denominador inflado.
- **Status leva semanas para resolver.** Um mês recente vem quase todo em
  `IN_REVIEW`; comparar a comissão aprovada de setembro com a de julho subestima
  setembro por construção. Por isso a comissão é reportada com o corte de status
  ao lado, e a série por mil envios usa o total de cliente.
- **Compra própria nunca entra.** `is_own_purchase` é excluída em todo cálculo.
- **Preço é o da publicação, não o de hoje.** Vem do `PriceHistoryEntry` mais
  recente até o envio (RESTR-05: uso interno; nada daqui vai para caption).
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from apps.analytics.models import MLAffiliateSale
from apps.curation.services.product_family import product_family_key
from apps.distribution.models import Delivery, SocialChannel
from apps.offers.models import PriceHistoryEntry

log = logging.getLogger(__name__)

DEFAULT_WEEKS = 8
DEFAULT_CHANNEL_CODE = 'whatsapp_principal'
ML_MARKETPLACE_CODE = 'mercadolivre'

# Faixas escolhidas para tornar visível a fronteira de R$ 500, que é onde os
# tetos de `max_price` mordiam. Não são quartis: são a linha do problema.
PRICE_BANDS: tuple[tuple[str, Decimal, Decimal | None], ...] = (
    ('até R$ 100', Decimal('0'), Decimal('100')),
    ('R$ 100 a 300', Decimal('100'), Decimal('300')),
    ('R$ 300 a 500', Decimal('300'), Decimal('500')),
    ('R$ 500 a 1.000', Decimal('500'), Decimal('1000')),
    ('acima de R$ 1.000', Decimal('1000'), None),
)

PATH_AI = 'curadoria_ia'
PATH_LEGACY = 'selector_legado'
PATH_LABELS = {
    PATH_AI: 'curadoria IA',
    PATH_LEGACY: 'selector legado',
}

# Status que o painel do ML ainda não resolveu. Reportado à parte porque é a
# maior fonte de leitura errada em janela recente.
STATUS_IN_REVIEW = 'IN_REVIEW'
STATUS_APPROVED = 'APPROVED'


@dataclass(frozen=True)
class BandRow:
    label: str
    deliveries: int
    deliveries_pct: float
    sales: int
    commission: Decimal
    commission_pct: float
    commission_per_thousand: Decimal


@dataclass(frozen=True)
class CategoryRow:
    code: str
    name: str
    deliveries: int
    deliveries_pct: float
    sales: int
    commission: Decimal


@dataclass(frozen=True)
class PathRow:
    code: str
    label: str
    deliveries: int
    deliveries_pct: float
    sales_matched: int
    commission: Decimal


@dataclass(frozen=True)
class GapRow:
    """Família de produto que vendeu na janela e que não publicamos nela."""

    family: str
    sales: int
    commission: Decimal
    sample_title: str


@dataclass
class RevenueLoopReport:
    start: date
    end: date
    channel_code: str
    deliveries_total: int
    deliveries_ml: int
    sales_total: int
    commission_total: Decimal
    commission_approved: Decimal
    commission_in_review: Decimal
    sales_in_review: int
    own_purchases_excluded: int
    category_resolved: int
    bands: list[BandRow] = field(default_factory=list)
    categories: list[CategoryRow] = field(default_factory=list)
    paths: list[PathRow] = field(default_factory=list)
    gaps: list[GapRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def commission_per_thousand(self) -> Decimal:
        return _per_thousand(self.commission_total, self.deliveries_ml)

    def as_dict(self) -> dict:
        return {
            'generated_at': timezone.now().isoformat(),
            'period': {'start': self.start.isoformat(), 'end': self.end.isoformat()},
            'channel': self.channel_code,
            'marketplace': ML_MARKETPLACE_CODE,
            'totals': {
                'deliveries_total': self.deliveries_total,
                'deliveries_ml': self.deliveries_ml,
                'sales': self.sales_total,
                'commission_total': str(self.commission_total),
                'commission_approved': str(self.commission_approved),
                'commission_in_review': str(self.commission_in_review),
                'sales_in_review': self.sales_in_review,
                'own_purchases_excluded': self.own_purchases_excluded,
                'commission_per_thousand': str(self.commission_per_thousand),
            },
            'bands': [
                {
                    'label': row.label,
                    'deliveries': row.deliveries,
                    'deliveries_pct': row.deliveries_pct,
                    'sales': row.sales,
                    'commission': str(row.commission),
                    'commission_pct': row.commission_pct,
                    'commission_per_thousand': str(row.commission_per_thousand),
                }
                for row in self.bands
            ],
            'categories': [
                {
                    'code': row.code,
                    'name': row.name,
                    'deliveries': row.deliveries,
                    'deliveries_pct': row.deliveries_pct,
                    'sales': row.sales,
                    'commission': str(row.commission),
                }
                for row in self.categories
            ],
            'category_coverage': {
                'resolved': self.category_resolved,
                'total': self.sales_total,
            },
            'paths': [
                {
                    'code': row.code,
                    'label': row.label,
                    'deliveries': row.deliveries,
                    'deliveries_pct': row.deliveries_pct,
                    'sales_matched': row.sales_matched,
                    'commission': str(row.commission),
                }
                for row in self.paths
            ],
            'gaps': [
                {
                    'family': row.family,
                    'sales': row.sales,
                    'commission': str(row.commission),
                    'sample_title': row.sample_title,
                }
                for row in self.gaps
            ],
            'warnings': self.warnings,
        }


def build_revenue_loop_report(
    weeks: int = DEFAULT_WEEKS,
    channel_code: str = DEFAULT_CHANNEL_CODE,
    end: date | None = None,
) -> RevenueLoopReport:
    """Monta o relatório da janela de `weeks` semanas terminando em `end`."""
    end = end or timezone.localdate()
    start = end - timedelta(weeks=weeks)

    channel = SocialChannel.objects.filter(code=channel_code).first()
    if channel is None:
        raise ValueError(f'Canal "{channel_code}" não encontrado (SocialChannel.code).')

    deliveries = list(
        Delivery.objects.filter(
            social_channel=channel,
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__date__gte=start,
            sent_at__date__lte=end,
        )
        .select_related('offer', 'offer__marketplace', 'offer__category')
        .prefetch_related(Prefetch('curated_batch_items'))
    )
    deliveries_ml = [
        d for d in deliveries
        if d.offer and d.offer.marketplace and d.offer.marketplace.code == ML_MARKETPLACE_CODE
    ]

    price_map = _published_price_map(deliveries_ml)

    sales_qs = MLAffiliateSale.objects.filter(
        sale_date__gte=start,
        sale_date__lte=end,
    ).select_related('offer', 'offer__category')
    own_purchases = sum(1 for s in sales_qs if s.is_own_purchase)
    sales = [s for s in sales_qs if not s.is_own_purchase]

    report = RevenueLoopReport(
        start=start,
        end=end,
        channel_code=channel_code,
        deliveries_total=len(deliveries),
        deliveries_ml=len(deliveries_ml),
        sales_total=len(sales),
        commission_total=_sum(s.commission_brl for s in sales),
        commission_approved=_sum(
            s.commission_brl for s in sales if s.status == STATUS_APPROVED
        ),
        commission_in_review=_sum(
            s.commission_brl for s in sales if s.status == STATUS_IN_REVIEW
        ),
        sales_in_review=sum(1 for s in sales if s.status == STATUS_IN_REVIEW),
        own_purchases_excluded=own_purchases,
        category_resolved=sum(1 for s in sales if s.offer_id and s.offer.category_id),
    )

    report.bands = _build_bands(deliveries_ml, price_map, sales)
    report.categories = _build_categories(deliveries_ml, sales)
    report.paths = _build_paths(deliveries_ml, sales)
    report.gaps = _build_gaps(deliveries_ml, sales)
    report.warnings = _build_warnings(report)
    return report


def _build_bands(deliveries, price_map, sales) -> list[BandRow]:
    delivered_by_band: dict[str, int] = {label: 0 for label, _, _ in PRICE_BANDS}
    sales_by_band: dict[str, int] = {label: 0 for label, _, _ in PRICE_BANDS}
    commission_by_band: dict[str, Decimal] = {
        label: Decimal('0') for label, _, _ in PRICE_BANDS
    }

    for delivery in deliveries:
        price = price_map.get(delivery.id)
        label = _band_label(price)
        if label:
            delivered_by_band[label] += 1

    for sale in sales:
        label = _band_label(sale.sale_value_brl)
        if label:
            sales_by_band[label] += 1
            commission_by_band[label] += sale.commission_brl or Decimal('0')

    total_deliveries = sum(delivered_by_band.values())
    total_commission = sum(commission_by_band.values(), Decimal('0'))

    return [
        BandRow(
            label=label,
            deliveries=delivered_by_band[label],
            deliveries_pct=_pct(delivered_by_band[label], total_deliveries),
            sales=sales_by_band[label],
            commission=commission_by_band[label],
            commission_pct=_pct(commission_by_band[label], total_commission),
            commission_per_thousand=_per_thousand(
                commission_by_band[label], delivered_by_band[label]
            ),
        )
        for label, _, _ in PRICE_BANDS
    ]


def _build_categories(deliveries, sales) -> list[CategoryRow]:
    delivered: dict[tuple[str, str], int] = {}
    sold: dict[tuple[str, str], list] = {}

    for delivery in deliveries:
        key = _category_key(delivery.offer)
        delivered[key] = delivered.get(key, 0) + 1

    for sale in sales:
        if not sale.offer_id:
            continue
        key = _category_key(sale.offer)
        sold.setdefault(key, []).append(sale)

    total_deliveries = sum(delivered.values())
    keys = set(delivered) | set(sold)
    rows = [
        CategoryRow(
            code=code,
            name=name,
            deliveries=delivered.get((code, name), 0),
            deliveries_pct=_pct(delivered.get((code, name), 0), total_deliveries),
            sales=len(sold.get((code, name), [])),
            commission=_sum(s.commission_brl for s in sold.get((code, name), [])),
        )
        for code, name in keys
    ]
    rows.sort(key=lambda row: (-row.commission, -row.deliveries))
    return rows


def _build_paths(deliveries, sales) -> list[PathRow]:
    """Separa os dois caminhos de publicação (item 9).

    A marca do caminho é estrutural: entrega ligada a um `CuratedBatchItem` veio
    da curadoria IA; entrega sem essa ligação saiu pelo selector legado, que é o
    fallback de quando a IA falha.
    """
    by_path: dict[str, list] = {PATH_AI: [], PATH_LEGACY: []}
    for delivery in deliveries:
        path = PATH_AI if delivery.curated_batch_items.all() else PATH_LEGACY
        by_path[path].append(delivery)

    offer_to_path = {
        delivery.offer_id: path
        for path, items in by_path.items()
        for delivery in items
    }
    sales_by_path: dict[str, list] = {PATH_AI: [], PATH_LEGACY: []}
    for sale in sales:
        path = offer_to_path.get(sale.offer_id)
        if path:
            sales_by_path[path].append(sale)

    total = sum(len(items) for items in by_path.values())
    return [
        PathRow(
            code=path,
            label=PATH_LABELS[path],
            deliveries=len(by_path[path]),
            deliveries_pct=_pct(len(by_path[path]), total),
            sales_matched=len(sales_by_path[path]),
            commission=_sum(s.commission_brl for s in sales_by_path[path]),
        )
        for path in (PATH_AI, PATH_LEGACY)
    ]


def _build_gaps(deliveries, sales, limit: int = 10) -> list[GapRow]:
    """Vendeu na janela e não publicamos nada da mesma família.

    É o padrão do caso Insider: o produto vende, a cobertura some, e ninguém vê
    porque venda e publicação nunca foram cruzadas.
    """
    published_families = {
        product_family_key(d.offer.title, d.offer.normalized_title or '')
        for d in deliveries
        if d.offer and d.offer.title
    }
    published_families.discard('')

    grouped: dict[str, list] = {}
    for sale in sales:
        if not sale.product_title:
            continue
        family = product_family_key(sale.product_title)
        if not family or family in published_families:
            continue
        grouped.setdefault(family, []).append(sale)

    rows = [
        GapRow(
            family=family,
            sales=len(items),
            commission=_sum(s.commission_brl for s in items),
            sample_title=items[0].product_title,
        )
        for family, items in grouped.items()
    ]
    rows.sort(key=lambda row: (-row.commission, -row.sales))
    return rows[:limit]


def _build_warnings(report: RevenueLoopReport) -> list[str]:
    warnings: list[str] = []

    if report.sales_total and report.sales_in_review:
        pct = _pct(report.sales_in_review, report.sales_total)
        if pct >= 30:
            warnings.append(
                f'{report.sales_in_review} de {report.sales_total} vendas ainda em '
                f'IN_REVIEW ({pct:.0f}%) — a comissão aprovada desta janela está '
                'subestimada por maturidade, não por performance.'
            )

    if report.sales_total and report.category_resolved < report.sales_total:
        warnings.append(
            f'Casamento venda↔oferta resolveu {report.category_resolved} de '
            f'{report.sales_total} vendas — o recorte por categoria é amostra, '
            'o por faixa de preço não depende disso.'
        )

    legacy = next((p for p in report.paths if p.code == PATH_LEGACY), None)
    if legacy and legacy.deliveries_pct >= 10:
        warnings.append(
            f'{legacy.deliveries_pct:.0f}% dos envios saíram pelo selector legado '
            '— o caminho que roda quando a curadoria IA falha (item 9).'
        )

    if report.own_purchases_excluded:
        warnings.append(
            f'{report.own_purchases_excluded} venda(s) de compra própria excluída(s) '
            'de todos os números.'
        )

    if not report.deliveries_ml:
        warnings.append(
            'Nenhum envio de Mercado Livre na janela — os cruzamentos ficam vazios.'
        )

    return warnings


def _published_price_map(deliveries) -> dict[int, Decimal | None]:
    """Preço de cada oferta no momento em que ela foi publicada.

    Cai para `Offer.current_price` quando não há ponto de histórico anterior ao
    envio — acontece com oferta coletada e publicada no mesmo ciclo.
    """
    offer_ids = {d.offer_id for d in deliveries if d.offer_id}
    if not offer_ids:
        return {}

    history: dict[int, list[tuple[datetime, Decimal]]] = {}
    entries = PriceHistoryEntry.objects.filter(
        offer_id__in=offer_ids
    ).order_by('offer_id', 'collected_at').values_list('offer_id', 'collected_at', 'price')
    for offer_id, collected_at, price in entries:
        history.setdefault(offer_id, []).append((collected_at, price))

    price_map: dict[int, Decimal | None] = {}
    for delivery in deliveries:
        price = None
        points = history.get(delivery.offer_id, [])
        for collected_at, value in points:
            if delivery.sent_at and collected_at <= delivery.sent_at:
                price = value
            else:
                break
        if price is None:
            price = delivery.offer.current_price if delivery.offer else None
        price_map[delivery.id] = price
    return price_map


def _category_key(offer) -> tuple[str, str]:
    if offer and offer.category_id and offer.category:
        return offer.category.code, offer.category.name
    return '(sem categoria)', '(sem categoria)'


def _band_label(value) -> str | None:
    if value is None:
        return None
    value = Decimal(value)
    for label, lower, upper in PRICE_BANDS:
        if value >= lower and (upper is None or value < upper):
            return label
    return None


def _sum(values) -> Decimal:
    return sum((v or Decimal('0') for v in values), Decimal('0'))


def _pct(part, total) -> float:
    if not total:
        return 0.0
    return round(float(part) * 100 / float(total), 1)


def _per_thousand(commission: Decimal, deliveries: int) -> Decimal:
    if not deliveries:
        return Decimal('0.00')
    return (commission * 1000 / Decimal(deliveries)).quantize(Decimal('0.01'))
