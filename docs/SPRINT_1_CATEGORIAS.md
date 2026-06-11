# Sprint 1 — Classificação de Categorias

## Resumo

Cada oferta capturada agora recebe uma `Category` no momento da ingestão. A classificação combina:

1. **Keyword no título normalizado** (fonte principal).
2. **Hint do scraper** (label de origem em `raw_payload.source_label`, ex: Amazon `DEAL_URLS`).
3. **Fallback** para `outros` quando nenhuma regra casa.

Pipeline de publicação atual não foi alterado em comportamento — `category` é metadata; o seletor de Sprint 2/3 vai consumir.

## Modelo de dados

### `apps.offers.models.Category`

| Campo | Tipo | Notas |
|---|---|---|
| `code` | SlugField unique | chave estável usada por config e código |
| `name` | CharField 120 | exibição |
| `weight` | PositiveSmallInt 1–10 | peso de prioridade (Sprint 3) |
| `is_test_controlled` | Bool | `True` em `saude_suplementacao` |
| `exposure_quota_pct` | Decimal 5,2 null | cota inicial sugerida (Sprint 6) |
| `is_active` | Bool | desabilita sem deletar |

### `apps.offers.models.Offer`

Adicionados:
- `category = FK(Category, null=True, on_delete=SET_NULL, related_name='offers')`
- `category_source = CharField(60, blank=True)` — origem da classificação
- Índice `(category,)`

## Taxonomia inicial (14 categorias)

| Code | Nome | Peso | Test ctrl | Cota % |
|---|---|---:|---|---:|
| casa_cozinha | Casa e Cozinha | 10 | — | 30 |
| moda_feminina | Moda Feminina | 9 | — | 15 |
| moda_masculina | Moda Masculina | 8 | — | 10 |
| infantil | Infantil | 8 | — | 15 |
| tecnologia_cotidiana | Tecnologia Cotidiana | 7 | — | 15 |
| beleza_cuidados | Beleza e Cuidados Pessoais | 7 | — | 10 |
| saude_suplementacao | Saúde e Suplementação | 5 | **sim** | 5 |
| pet | Pet | 4 | — | — |
| bebidas | Bebidas | 3 | — | — |
| automotivo | Automotivo | 3 | — | — |
| outros | Outros | 2 | — | — |
| ferramentas | Ferramentas | 1 | — | — |
| construcao | Construção | 1 | — | — |
| industrial | Industrial | 1 | — | — |

`bebidas` foi adicionada além das 13 do prompt para acomodar "Vinhos" e "Bebidas Alcoólicas" do Amazon `DEAL_URLS`, evitando que caíssem em `outros`. Cotas das categorias frias permanecem `null` — preenchidas formalmente na Sprint 6.

## Componentes

| Arquivo | Função |
|---|---|
| `apps/offers/models.py` | `Category` + FK em `Offer` |
| `apps/offers/migrations/0004_*.py` | Schema (Category, FK, índice) |
| `apps/offers/migrations/0005_seed_categories.py` | Seed das 14 categorias |
| `apps/curation/services/classifier.py` | `classify()`, `apply_classification()`, dicionário de keywords, hint map |
| `apps/offers/services/repository.py` | Hook em `save_normalized_offer` invoca `apply_classification` |
| `scrapers/amazon.py` | `AmazonOffer.source_label` propagado no payload |
| `apps/offers/admin.py` | `CategoryAdmin` + colunas `category` e `category_source` no `OfferAdmin` |

## Feature flag

Chave em `apps.panel.Setting`:

- `categories_enabled` (default `1`) — quando `0`, `apply_classification` sai sem persistir nada. Ofertas continuam sendo salvas; só não recebem categoria. Mecanismo de rollback runtime sem deploy.

## Logs

Logger `apps.curation.classifier`, formato:

```
classifier_applied offer_id=<id> marketplace=<code> category=<code> source=<src> terms=[...] title=<...>
```

Onde `source` ∈ {`keyword:title`, `hint:source_label`, `fallback:outros`}.

## Critérios de aceite (verificados)

- [x] Toda nova oferta recebe uma categoria (hook em `save_normalized_offer`).
- [x] Ofertas sem correspondência caem em `outros`.
- [x] `classify()` é função pura, testável isoladamente.
- [x] Classificação rastreável via logger `apps.curation.classifier`.
- [x] Migração com seed das 14 categorias (`update_or_create` — idempotente).
- [x] Compatibilidade com ofertas antigas: `category` é `null=True`. Backfill manual via shell processou 5524 ofertas existentes.
- [x] `python3 manage.py check` sem erros.

## Backfill em ofertas existentes

```bash
python3 manage.py shell -c "
from apps.offers.models import Offer
from apps.curation.services.classifier import apply_classification
for o in Offer.objects.select_related('marketplace').filter(is_active=True).iterator():
    apply_classification(o)
"
```

Resultado da execução em 2026-06-04:
- 5524 ofertas processadas
- 2294 (41.5%) classificadas por keyword
- 3230 (58.5%) fallback `outros` — sinal para ampliar dicionário nas próximas sprints

## Rollback

### Reverter classificação em runtime (sem deploy)

```python
from apps.panel.models import Setting
Setting.objects.update_or_create(key='categories_enabled', defaults={'value': '0'})
```

Novas ofertas continuam sendo salvas, sem categoria atribuída. Ofertas antigas mantêm a categoria atribuída no último backfill.

### Reverter schema (descartar tabela e campos)

```bash
python3 manage.py migrate offers 0003_backfill_compliance_fields
```

Desfaz `0005` (apaga as 14 categorias seedadas) e `0004` (remove FK, índice, `category_source` e a tabela `Category`).

### Reverter scraper

`scrapers/amazon.py` — campo `source_label` no `AmazonOffer` tem default `''`. Removê-lo é seguro: o normalizer não exige `source_label`. Não há lock-in.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Classificador erra categoria de oferta nicho | `category_source` registra origem; admin permite override manual; dicionário evolui sem alteração de schema |
| 58.5% caindo em `outros` | Esperado na primeira rodada — ampliar `KEYWORDS` em PR pequeno, sem migração |
| Bug futuro em `apply_classification` quebra ingestão | Hook protegido por `try/except` em `repository._classify` — falha apenas degrada classificação, não quebra `save_normalized_offer` |
| Categoria deletada por engano no admin | `on_delete=SET_NULL` — ofertas perdem categoria mas não são apagadas |
| Conflito de keywords entre categorias | `_pick_best_match` ranqueia por quantidade de termos casados e prioridade fixa; determinístico |

## Próximas sprints (links)

- **Sprint 2** — Score multidimensional 30/30/20/10/10 (consome `Category.weight`).
- **Sprint 3** — Pesos por categoria já estão no model; resta expor configuração mais granular.
- **Sprint 5** — Scrapers segmentados (Mercado Livre ainda raspa página genérica `/ofertas`).
