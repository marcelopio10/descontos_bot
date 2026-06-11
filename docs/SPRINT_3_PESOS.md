# Sprint 3 — Pesos por Categoria

## Resumo

A base estrutural já foi entregue na Sprint 1 (`Category.weight` no model, seed dos pesos do prompt) e Sprint 2 (`_category_weight_factor` consome o peso no critério "categoria" 10% e no fator "popularidade" 30%). Esta sprint fecha o ciclo:

1. **Override de pesos via Setting** — ajuste em runtime sem precisar editar registros de `Category` (útil para A/B test rápido por ciclo, sem migração).
2. **Service de resolução** `resolve_category_weight()` — fonte única consultada pelo score.
3. **Comando `ranking_categorias`** — visibilidade operacional do estado atual (peso efetivo, ofertas ativas, score médio, distribuição de decisão).
4. **Seed das chaves de configuração** — `seed_settings` agora cria/atualiza as flags das Sprints 1–3 (`categories_enabled`, `use_category_score`, `min_quality_score`, `priority_quality_score`, `category_weights`).

## Pesos iniciais (já no banco desde a Sprint 1)

| Code | Peso | Notas |
|---|---:|---|
| casa_cozinha | 10 | |
| moda_feminina | 9 | |
| moda_masculina | 8 | |
| infantil | 8 | |
| tecnologia_cotidiana | 7 | |
| beleza_cuidados | 7 | |
| saude_suplementacao | 5 | **teste controlado** |
| pet | 4 | |
| automotivo | 3 | |
| bebidas | 3 | |
| outros | 2 | |
| ferramentas | 1 | |
| construcao | 1 | |
| industrial | 1 | |

Saúde e Suplementação fica em 5 e com `is_test_controlled=True` (multiplicador 0.85 no score por viés do dono). Conforme regra do prompt.

## Como ajustar pesos

### Opção 1 — Banco (persistente, padrão)

Django Admin → Categorias → editar `weight` (1–10). Vale para todas as ofertas a partir do próximo ciclo de classificação/scoring.

### Opção 2 — Override runtime via Setting (decisão R11)

Django Admin → Configurações → chave `category_weights` → JSON:

```json
{
  "saude_suplementacao": 3,
  "casa_cozinha": 8,
  "pet": 6
}
```

- Sobrescreve apenas os códigos listados.
- Não muda o banco — quando o Setting for esvaziado (`{}`), o peso volta ao valor de `Category.weight`.
- Pesos fora de [1, 10] são clampados.
- Valores inválidos no JSON são ignorados (fallback silencioso para o banco).

Use para teste A/B por ciclo sem perder a configuração principal.

## Service

`apps/curation/services/category_weights.py`

| Função | Retorno | Notas |
|---|---|---|
| `resolve_category_weight(category)` | `int` | Override > Category.weight > default 5 |
| `get_all_weights()` | `dict[code, int]` | Peso efetivo de todas as categorias ativas |
| `get_override_map()` | `dict[code, int]` | Apenas os códigos com override ativo |

Consumido pelo `quality_score._category_weight_factor`. Único ponto de leitura — Sprint 6 e 7 vão reutilizar.

## Comando `ranking_categorias`

```bash
python3 manage.py ranking_categorias            # todas as ofertas ativas
python3 manage.py ranking_categorias --fresh-only  # apenas dentro do gate de freshness
python3 manage.py ranking_categorias --limit 100   # acelera diagnóstico em base grande
```

Saída inclui peso do banco, peso efetivo (com marcador `*` para override), marcador `T` para teste controlado, contagem de ofertas, score médio e distribuição de decisão (`publicar`/`fila_secundaria`/`descartar`).

Exemplo real (5524 ofertas ativas):

```
code                     peso_db  peso_efetivo  ofertas  score_médio  decisões
casa_cozinha                  10         10         619         2.15  descartar=619
moda_masculina                 8          8         314         3.30  descartar=311, fila_secundaria=2, publicar=1
saude_suplementacao            5          5 T       163         5.49  descartar=162, fila_secundaria=1
...
outros                         2          2        3230         2.65  descartar=3229, fila_secundaria=1
```

## Componentes implementados

| Arquivo | Função |
|---|---|
| `apps/curation/services/category_weights.py` | `resolve_category_weight`, override JSON, clamp |
| `apps/curation/services/quality_score.py` | `_category_weight_factor` agora delega ao service |
| `apps/curation/management/__init__.py` | scaffolding |
| `apps/curation/management/commands/__init__.py` | scaffolding |
| `apps/curation/management/commands/ranking_categorias.py` | comando operacional |
| `apps/panel/management/commands/seed_settings.py` | acrescenta chaves Sprint 1–3 |

## Critérios de aceite (verificados)

- [x] Sistema ordena ofertas pelo score final (Sprint 2 já entregou — `selector.py` ordena por `score`).
- [x] Pesos fáceis de alterar sem mudança profunda: admin Category (banco) ou Setting `category_weights` (override runtime).
- [x] Categorias de baixa aderência naturalmente perdem prioridade (ranking real mostra `outros`/`industrial`/`construcao` em score médio < 3).
- [x] `python3 manage.py check` sem erros.
- [x] Comando operacional disponível.

## Rollback

### Runtime — desligar override

```python
from apps.panel.models import Setting
Setting.objects.filter(key='category_weights').update(value='{}')
```

Pesos voltam ao banco imediatamente.

### Banco — restaurar pesos seed da Sprint 1

```bash
python3 manage.py migrate offers 0004_category_offer_category_source_and_more
python3 manage.py migrate offers 0005_seed_categories
```

Re-executa o `update_or_create` da seed (idempotente — restaura pesos originais).

### Código

Sprint 3 não altera schema. Reverter é só `git revert`. Score continua funcionando — `_category_weight_factor` cai no fallback `category.weight` se o service for removido.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| JSON inválido em `category_weights` quebra score | `_get_overrides` retorna `{}` em parse falhado; cada valor inválido é ignorado individualmente |
| Override com valor fora de [1,10] | Clamp em `_clamp` (limita silenciosamente) |
| Operador esquece override ativo e estranha distribuição | `ranking_categorias` mostra marcador `*` e lista overrides ativos no rodapé |
| Categoria nova adicionada sem peso | Default 5 via `DEFAULT_WEIGHT` em `category_weights.py` |

## Próximas sprints (impacto)

- **Sprint 4** — Filtros de qualidade ampliam blacklist + reduzem score em padrões B2B. Score multiplicativo já habilitado.
- **Sprint 6** — Lê `Category.exposure_quota_pct` (já no model) para controlar cota por ciclo.
- **Sprint 7** — Feedback loop pode reescrever `category_weights` via Setting com base em dados reais.
