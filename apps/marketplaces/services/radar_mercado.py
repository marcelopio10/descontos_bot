"""Radar de mercado (Sprint 6 / achado P7): ranking de vendas Shopee, 1x/dia.

Reaproveita `ProductOfferCollector` (`shopee_collectors.py`) para estimar um
`escore_venda` (0..1) por categoria interna e por produto, usado como sinal
*opcional* de bônus em `apps.curation.services.quality_score` e no payload de
curadoria da IA (`apps.curation.services.ai_prompt.build_ai_curation_payload`,
campo `market_radar`).

Limitações conhecidas (best-effort, documentadas em vez de resolvidas aqui —
mesmo espírito de `shopee_collectors.py`, que já assume que "o schema exato é
confirmado contra a conta real na 1ª execução com credenciais"):

1. Não existe mapeamento oficial confirmado entre `productCatId` (Shopee) e
   as `Category` internas do projeto. Por isso o radar consulta por
   `keyword=<nome da categoria>` (ex.: "Casa e Cozinha") em vez de por
   `productCatId` — aproxima por texto, não por taxonomia.
2. Não há documentação pública nem interna confirmando o significado exato
   dos inteiros de `sortType`/`listType` da Shopee Affiliate API. O único
   valor com semântica confirmada no projeto hoje é `sortType=2` = "maior
   comissão" (ver `scrapers/shopee.py:DEFAULT_SORT_TYPE`) — não é o que
   queremos para um radar de vendas. Como não há confirmação de qual valor
   equivale a "mais vendidos", o radar NÃO aposta a ordenação em
   `sortType` (usa o default da API, `RADAR_SORT_TYPE = None`): ele SEMPRE
   reordena localmente pelos valores de `sales` devolvidos por item, que é
   o único dado observável e verificável para "o que vendeu mais". Se uma
   futura validação com credenciais reais (mesmo processo do Sprint 7B.3)
   confirmar o valor certo de sortType, isso só melhora a cobertura da
   busca — não é pré-requisito para o `escore_venda` estar correto.
3. É best-effort e tolerante a falha por categoria: uma categoria que falha
   (timeout, erro de rede, resposta vazia) não derruba o radar inteiro, só
   reduz a cobertura do dia (loga e segue para a próxima).

Persistência: propositalmente NÃO criamos um novo modelo de banco para
guardar o histórico do radar. `RadarMercadoResult` é recalculado a cada
chamada e vive só na memória do processo que o invoca (o próprio ciclo de
curadoria roda a coleta de novo quando precisa do sinal, e o comando
`coletar_radar_mercado` existe para inspeção manual 1x/dia). O volume atual
(poucas dezenas de categorias, 1x/dia) não justifica série temporal
persistida; se isso mudar, aí sim vale um modelo dedicado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.marketplaces.services.shopee_collectors import ProductOfferCollector
from apps.offers.models import Category

log = logging.getLogger('apps.marketplaces.radar_mercado')

# best-effort: ver limitação (2) no docstring do módulo. `sortType=2` já tem
# semântica confirmada no projeto ("maior comissão", scrapers/shopee.py) e
# não é o que queremos aqui, então evitamos reutilizá-lo; `None` deixa a
# Shopee aplicar o default dela. A ordenação que de fato importa para o
# `escore_venda` vem da reordenação local pelo campo `sales` (ver
# `collect_radar_mercado`), não deste valor.
RADAR_SORT_TYPE: int | None = None
RADAR_LIST_TYPE: int | None = 0  # mesmo default já usado em scrapers/shopee.py (DEFAULT_LIST_TYPE)

DEFAULT_TOP_N_CATEGORIES = 15  # limita chamadas à API por ciclo (categorias de maior peso primeiro)
DEFAULT_LIMIT_PER_CATEGORY = 20
DEFAULT_TOP_N_PRODUCTS = 20

_DISABLED_LIMITATIONS = (
    'SHOPEE_AFFILIATE_ENABLED=false: radar não executado, resultado neutro '
    '(mesmo gate de produção usado na Tarefa 4.1 / link_builder.py).'
)
_BEST_EFFORT_LIMITATIONS = (
    'best-effort (Sprint 6 / achado P7): sortType/listType da Shopee '
    'Affiliate API sem doc oficial confirmada para "mais vendidos" — '
    'escore_venda calculado localmente a partir do campo `sales` de cada '
    'item, não da ordenação devolvida pela API. Categoria Shopee '
    '(productCatId) não é mapeada 1:1 para Category interna; usa '
    'keyword=nome da categoria como aproximação textual.'
)


@dataclass(frozen=True)
class RadarMercadoResult:
    enabled: bool
    collected_at: str
    category_scores: dict[str, float] = field(default_factory=dict)
    product_scores: dict[str, float] = field(default_factory=dict)
    sample_size: int = 0
    categories_covered: list[str] = field(default_factory=list)
    limitations: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {
            'enabled': self.enabled,
            'collected_at': self.collected_at,
            'category_scores': dict(self.category_scores),
            'product_scores': dict(self.product_scores),
            'sample_size': self.sample_size,
            'categories_covered': list(self.categories_covered),
            'limitations': self.limitations,
        }


def collect_radar_mercado(
    *,
    categories: list[Category] | None = None,
    collector: ProductOfferCollector | None = None,
    top_n_categories: int = DEFAULT_TOP_N_CATEGORIES,
    limit_per_category: int = DEFAULT_LIMIT_PER_CATEGORY,
    top_n_products: int = DEFAULT_TOP_N_PRODUCTS,
) -> RadarMercadoResult:
    """Coleta o ranking de vendas Shopee do dia e gera `escore_venda` por categoria/produto.

    Gate OBRIGATÓRIO (mesma razão de proteção de produção da Tarefa 4.1):
    com `settings.SHOPEE_AFFILIATE_ENABLED` desligado (default real de
    produção hoje), retorna um resultado vazio/neutro sem consultar banco
    nem API — não muda nada em produção enquanto a flag estiver off.
    """
    now_iso = timezone.now().isoformat()
    if not getattr(settings, 'SHOPEE_AFFILIATE_ENABLED', False):
        return RadarMercadoResult(enabled=False, collected_at=now_iso, limitations=_DISABLED_LIMITATIONS)

    target_categories = (
        categories
        if categories is not None
        else list(Category.objects.filter(is_active=True).order_by('-weight', 'name')[:top_n_categories])
    )
    active_collector = collector or ProductOfferCollector()

    raw_category_sales: dict[str, int] = {}
    product_sales: dict[str, int] = {}
    covered: list[str] = []
    sample_size = 0

    for category in target_categories:
        keyword = (category.name or '').strip()
        if not keyword:
            continue
        try:
            nodes = active_collector.fetch(
                keyword=keyword,
                limit=limit_per_category,
                sort_type=RADAR_SORT_TYPE,
                list_type=RADAR_LIST_TYPE,
            )
        except Exception as exc:  # pragma: no cover - defensivo: 1 categoria não derruba o radar
            log.warning('radar_mercado_categoria_falhou categoria=%s erro=%s', category.code, exc)
            continue

        covered.append(category.code)
        category_total = 0
        for node in nodes:
            sample_size += 1
            sales = _safe_int(node.get('sales'))
            category_total += sales
            product_name = str(node.get('productName') or '').strip()
            if product_name:
                key = product_name[:120]
                product_sales[key] = max(product_sales.get(key, 0), sales)
        raw_category_sales[category.code] = raw_category_sales.get(category.code, 0) + category_total

    top_products = dict(sorted(product_sales.items(), key=lambda item: item[1], reverse=True)[:top_n_products])

    return RadarMercadoResult(
        enabled=True,
        collected_at=now_iso,
        category_scores=_normalize(raw_category_sales),
        product_scores=_normalize(top_products),
        sample_size=sample_size,
        categories_covered=covered,
        limitations=_BEST_EFFORT_LIMITATIONS,
    )


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _normalize(raw: dict[str, int]) -> dict[str, float]:
    if not raw:
        return {}
    maximum = max(raw.values())
    if maximum <= 0:
        return {key: 0.0 for key in raw}
    return {key: round(value / maximum, 4) for key, value in raw.items()}
