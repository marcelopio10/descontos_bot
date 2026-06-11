# Sprint 2 — Score de Relevância da Oferta

## Resumo

Cada oferta recebe um score 0–100 calculado por 5 componentes ponderados (fórmula obrigatória do prompt: 30/30/20/10/10) e modulado por multiplicadores (gate de qualidade) fora dos 100 pontos. O resultado é uma classificação em quatro faixas (`excelente`/`boa`/`mediana`/`fraca`) e uma decisão (`prioritizar`/`publicar`/`fila_secundaria`/`descartar`).

API pública preservada: `quality_score(offer)` e `quality_score_breakdown(offer)`. Selector e admin continuam funcionando — só passam a ver score multidimensional.

## Fórmula

```
score = (
    0.30 * desconto_norm
  + 0.30 * popularidade_norm
  + 0.20 * avaliacoes_norm
  + 0.10 * preco_norm
  + 0.10 * categoria_norm
) * 100
```

Cada componente é normalizado para [0, 1] antes da multiplicação pelo peso (cálculo final equivale a usar pesos absolutos 30/30/20/10/10, total 100).

Score final = score base × ∏ multiplicadores × ∏ penalidades (todos no intervalo [0, 1]).

## Componentes normalizados

| Componente | Sinal | Notas |
|---|---|---|
| **discount** | `discount_pct` | escala linear 0–50%, saturação até 85%, decai 85–99%, zera acima de 99% |
| **popularity** | categoria(50%) + marca(30%) + bestseller(20%) | marca via dicionário `STRONG_BRANDS`; bestseller via `raw_payload.source_label` |
| **reviews** | `review_rating` + `review_count` | fallback neutro 0.5 quando ausente (não premia ausência, não pune); 0.7 rating + 0.3 contagem log |
| **price** | `current_price` | faixa familiar R$30–R$150 = 1.0; cai gradualmente fora |
| **category** | `category.weight` | peso 1–10 da Sprint 3 → peso/10. Fonte única (decisão R5) |

## Multiplicadores (gate fora dos 100 pontos — decisão R3)

| Nome | Fator | Quando |
|---|---:|---|
| `marketplace_trust` | 1.0 (Amazon) / 0.95 (ML) / 0.85 (outros) | sempre |
| `recency` | 0..1 | linear sobre `SITE_OFFER_MAX_AGE_HOURS` (default 36h). Ofertas antigas → score 0. |
| `test_controlled_confidence` | 0.85 | apenas em `category.is_test_controlled=True` (suplementos: viés do dono) |

## Penalidades (existentes do score legado, mantidas)

| Nome | Fator | Quando |
|---|---:|---|
| `no_image` | 0.7 | `image_url` vazio |
| `suspect_original_price` | 0.5 | `original_price / current_price >= 20` |
| `extreme_discount` | 0.0 | `discount_pct > 99` |

## Faixas e decisão

| Score | Classificação | Decisão |
|---|---|---|
| 85–100 | excelente | prioritizar |
| 70–84 | boa | publicar |
| 55–69 | mediana | fila_secundaria |
| 0–54 | fraca | descartar |

## Threshold soft (decisão R9)

Settings em `apps.panel.Setting`:

| Chave | Default | Significado |
|---|---:|---|
| `min_quality_score` | 55 | abaixo disso: descarta no selector |
| `priority_quality_score` | 70 | atinge: vai ao topo da fila |

Sprint 2 sobe o `min_quality_score` default de 0 para 55. Compatibilidade: ainda lido via `get_decimal_setting`. Operador pode ajustar via admin sem deploy.

## Tratamento de suplementos (decisão de produto)

Não excluir, não priorizar. Apenas multiplicador `test_controlled_confidence=0.85` aplicado sempre que `category.is_test_controlled=True`. Limita exposição automática enquanto a Sprint 7 não trouxer feedback real (cliques/conversões de membros).

## Componentes implementados

| Arquivo | Função |
|---|---|
| `apps/offers/models.py` | Campos `review_rating` + `review_count` no Offer |
| `apps/offers/migrations/0006_add_review_fields.py` | Migration nullable (compatível) |
| `apps/offers/services/normalizer.py` | `NormalizedOffer.review_rating/_count` + parsers `_to_optional_rating`, `_to_optional_count` |
| `apps/offers/services/repository.py` | Persiste `review_rating` e `review_count` no `defaults` |
| `scrapers/amazon.py` | `_extract_reviews` na listagem (selector `.a-icon-alt`, `.a-size-base.s-underline-text`) |
| `scrapers/mercado_livre.py` | `_extract_reviews` (`.poly-reviews__rating`, `.poly-reviews__total`) |
| `apps/curation/services/quality_score.py` | Reescrita: 5 componentes + multiplicadores + classificação. Legado preservado atrás de flag |
| `apps/curation/services/selector.py` | Threshold soft (`min_quality_score` 55 + `priority_quality_score` 70), log estruturado de decisão |
| `apps/offers/admin.py` | Colunas `review_rating`, `review_count`, `classification_column` |

## Feature flag

Setting `use_category_score` (default `1` → score novo ativo). Quando `0`, `quality_score_breakdown` cai no algoritmo legado (mesmo arquivo, função `_legacy_breakdown`) — preserva 100% do comportamento pré-Sprint 2 para rollback instantâneo.

## Logs

Logger `apps.curation.selector`:

```
selector_pick offer_id=<id> score=<n> classification=<c> decision=<d> category=<code> marketplace=<mk> discount=<pct>
selector_drop offer_id=<id> score=<n> decision=descartar classification=<c> category=<code>
```

Logger `apps.curation.classifier` (Sprint 1) continua emitindo a categorização.

## Critérios de aceite (verificados)

- [x] Toda oferta recebe score 0–100.
- [x] Pesos obrigatórios 30/30/20/10/10 aplicados.
- [x] Faixa e decisão expostas em `ScoreBreakdown.classification` e `.decision`.
- [x] Ofertas abaixo de `min_quality_score` (default 55) são descartadas no selector com log.
- [x] Ofertas acima de `priority_quality_score` (default 70) vão para o topo da fila.
- [x] Suplementos aplicam `test_controlled_confidence=0.85`.
- [x] Score legado preservado via feature flag.
- [x] `python3 manage.py check` sem erros.
- [x] `makemigrations --dry-run` = `No changes detected`.

## Distribuição observada (5524 ofertas ativas em 2026-06-04)

- **Frescas (≤36h, dentro do gate de recency):** 731 ofertas, score médio 22.0, 99.3% em `fraca`.
- **Antigas (>36h):** recency multiplica por 0 → score 0.
- **Razões para o volume alto em `fraca`:**
  - 58% das ofertas históricas caem em `outros` (Sprint 1 — dicionário raso).
  - Ofertas legadas têm `review_rating=null` (scraper só extrai a partir desta sprint).
  - Categoria `outros` tem peso 2/10 → `popularity`+`category` baixos.

**Esse é o comportamento esperado da Sprint 2.** O volume publicável crescerá quando:
- Dicionário de keywords do classifier for ampliado (PR pequeno, sem migração).
- Sprint 5 trouxer scrapers segmentados por categoria quente.
- Novos ciclos de scraping povoarem `review_rating`/`review_count`.

## Rollback

### Runtime — desligar score novo

```python
from apps.panel.models import Setting
Setting.objects.update_or_create(
    key='use_category_score',
    defaults={'value': '0', 'description': 'Sprint 2 desligada — volta ao score legado'},
)
```

`quality_score_breakdown` passa a usar `_legacy_breakdown`. Selector e admin continuam vendo `ScoreBreakdown` com a mesma forma.

### Runtime — relaxar threshold

```python
Setting.objects.update_or_create(key='min_quality_score', defaults={'value': '0'})
```

Volta ao comportamento pré-Sprint 2 (sem corte por score).

### Schema — reverter rating fields

```bash
python3 manage.py migrate offers 0005_seed_categories
```

Remove `review_rating` e `review_count`. Compatível: campos nullable, sem perda de dado essencial.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Threshold 55 corta volume publicável drasticamente | Soft default; ajustável via Setting; rollback instantâneo |
| Ofertas antigas sem rating ficam permanentemente penalizadas | `_score_reviews` retorna 0.5 quando ambos são None (neutro, não punitivo) |
| Dicionário de marcas (`STRONG_BRANDS`) pode estar incompleto | Marca ausente → componente popularity cai para 0.55 (default) — degradação graciosa, sem zerar |
| Extração de rating no scraper pode falhar em layout novo do marketplace | Try/except amplo no scraper retorna `(0.0, 0)`; normalizer aceita None |
| Recency mata score de ofertas que ainda estão no banco mas são antigas | Esperado — Sprint 4 vai endurecer ainda mais a expiração; o seletor já não as enviaria por outras regras |
| Categoria `outros` recebe peso 2 (Sprint 1 default) | Sprint 3 permite ajustar todos os pesos via admin sem migração |

## Próximas sprints (impacto)

- **Sprint 3** — Pesos por categoria editáveis em runtime. Toda a fonte do `category` component já lê `category.weight` — Sprint 3 só expõe melhor a UI.
- **Sprint 4** — Filtros de qualidade. Vai usar `is_test_controlled` e ampliar `STRONG_BRANDS` / blacklist.
- **Sprint 5** — Scrapers segmentados. Aumenta volume nas categorias quentes (sobe `category` e `popularity`).
- **Sprint 6** — Controle de exposição. Vai ler `category.exposure_quota_pct` durante a seleção.
- **Sprint 7** — Feedback loop. Vai reescrever `_score_popularity` para considerar histórico de cliques.
