# Sprint 5 — Scrapers Orientados a Categorias

## Resumo

Scrapers ganham caminho complementar guiado por **configuração declarativa**, sem remover o caminho atual:

- **Estado atual** (`scrape_daily_deals`) continua intacto.
- **Estado novo** (`scrape_categories`) lê URLs por categoria de `scrapers/category_targets.py`, propaga `category_hint` no payload e respeita critérios mínimos por categoria.
- Adapter escolhe a estratégia em runtime via flag `category_scraping_enabled`. Default `0` (genérico) — Sprint 5 chega desligada e é ligada operacionalmente.

Mercado Livre sai da página única `/ofertas?page=N` quando o flag é ligado e passa a iterar listagens segmentadas (`lista.mercadolivre.com.br/<seção>/_DiscountRange_...`). Amazon ganha categorias específicas além do que já existia em `DEAL_URLS`.

## Configuração declarativa

`scrapers/category_targets.py` define, para cada par `(marketplace, categoria)`:

| Chave | Tipo | Função |
|---|---|---|
| `urls` | `list[(label, url)]` | URLs específicas da categoria |
| `priority_brands` | `tuple[str]` | informativo (consumido indiretamente pelo score) |
| `min_discount` | `int` | filtro pós-extração |
| `max_price` | `float \| None` | filtro pós-extração |
| `cycle_limit` | `int` | corte por categoria/ciclo (controle de exposição) |
| `fallback` | `'generic' \| 'skip'` | comportamento se URL falhar (informativo nesta sprint) |

Categorias cobertas: `casa_cozinha`, `moda_feminina`, `moda_masculina`, `infantil`, `tecnologia_cotidiana`, `beleza_cuidados`, `saude_suplementacao`. Total: **13 URLs Amazon + 12 URLs ML**.

Saúde e Suplementação têm `cycle_limit=5` (Amazon e ML) — exposição limitada conforme prompt (viés do dono). `fallback='skip'` para sinalizar que a categoria não recua para genérico.

## Fluxo

```
Adapter.collect(max_pages)
  └─ category_scraping_enabled?
       ├─ sim → scraper.scrape_categories(targets)
       │         └─ _apply_category_filters(marketplace, payloads)
       │              └─ filtra por min_discount, max_price, cycle_limit
       │
       └─ não → scraper.scrape_daily_deals(max_pages)   # comportamento atual
```

`scrape_categories` injeta dois campos no payload:
- `source_label` — rótulo amigável da URL (já existia desde Sprint 1 no Amazon).
- `category_hint` — `category_code` da config.

O `classifier.apply_classification` reconhece `category_hint` e atribui categoria **antes** de tentar keyword/source_label. Source: `hint:scraper_target`. Confiança alta — a oferta veio de URL específica daquela categoria.

## Critérios mínimos pós-extração

Aplicados em `_apply_category_filters` (adapter), com log de drop:

```
category_scraping_summary marketplace=amazon kept=42 per_category={'casa_cozinha': 18, ...} dropped={'saude_suplementacao:cycle_limit': 12, ...}
```

Ofertas sem `category_hint` passam ilesas e seguem para o classifier por keyword/fallback (Sprint 1).

## Comparativo entre estratégias

Novo comando:

```bash
python3 manage.py captura_por_categoria --hours 24
```

Mostra:
1. Distribuição por marketplace × categoria.
2. Distribuição por origem da classificação (`keyword:title`, `fallback:outros`, `hint:source_label`, `hint:scraper_target`).
3. Marketplace × origem.

`hint:scraper_target` indica oferta capturada pela estratégia da Sprint 5. Operador compara volume de cada origem após ligar/desligar a flag.

Snapshot pré-Sprint 5 (últimas 168h, flag ainda desligada):
- Total: 1938 ofertas
- `fallback:outros`: 1112 (57%)
- `keyword:title`: 826 (43%)
- `hint:scraper_target`: 0

A diferença entre os dois últimos é a métrica direta de ganho da Sprint 5: ofertas que antes caíam em `outros` por falta de sinal vão passar a entrar com `hint:scraper_target` em categorias quentes.

## Componentes implementados

| Arquivo | Função |
|---|---|
| `scrapers/category_targets.py` (novo) | Config declarativa + `CategoryTarget`, `get_targets`, `flatten_urls` |
| `scrapers/amazon.py` | `scrape_categories(targets)` + refactor `_scrape_urls` (genérico ainda funciona) |
| `scrapers/mercado_livre.py` | `scrape_categories(targets)` paralelo a `scrape_daily_deals` |
| `apps/scraping/services/adapters.py` | Roteamento por flag + `_apply_category_filters` |
| `apps/curation/services/classifier.py` | Honra `category_hint`; nova source `hint:scraper_target` |
| `apps/scraping/management/commands/captura_por_categoria.py` (novo) | Métricas comparativas |
| `apps/panel/management/commands/seed_settings.py` | Chave `category_scraping_enabled` |

## Critérios de aceite (verificados)

- [x] Captura intencional em categorias prioritárias (7 categorias × 2 marketplaces).
- [x] Scraper genérico preservado (`scrape_daily_deals` não removido nem alterado em comportamento).
- [x] Possível comparar performance entre estratégias (comando dedicado, sources distintas no `category_source`).
- [x] Critérios por categoria aplicados (smoke: 7 cases sintéticos comportaram-se conforme regras `min_discount`/`max_price`/`cycle_limit`).
- [x] Saúde com exposição limitada (`cycle_limit=5`).
- [x] `manage.py check` sem erros. `makemigrations --dry-run` = `No changes detected`.

## Ligando em produção

Sprint 5 chega desligada. Ligar quando confortável:

```python
from apps.panel.models import Setting
Setting.objects.update_or_create(
    key='category_scraping_enabled',
    defaults={'value': '1'},
)
```

Próximo ciclo de scraping passa a usar `scrape_categories`. Rodar `captura_por_categoria --hours 6` após o primeiro ciclo para validar.

## Rollback

### Runtime — voltar ao scraper genérico

```python
Setting.objects.update_or_create(
    key='category_scraping_enabled',
    defaults={'value': '0'},
)
```

Próximo ciclo volta a `scrape_daily_deals`. Sem perda de dados — as ofertas já capturadas continuam no banco.

### Código

`git revert` é seguro. Sem schema. Compatibilidade preservada — `scrape_daily_deals` continua sendo o caminho default.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| URL nova do marketplace muda layout e quebra parse | Reuso de `_extract_cards`/`_extract_poly_cards` — seletores idênticos ao genérico. Falhas isoladas logam e continuam |
| Banimento por aumento de requests (25 URLs Amazon + 12 ML) | Delays mantidos (`DELAY_MIN..DELAY_MAX`); cada categoria pode falhar isolada sem matar o ciclo; CAPTCHA detector já existe |
| `cycle_limit=5` em suplementos pode subestimar demanda real | Setting permite override total dos targets via edição do arquivo + deploy; volume controlado pelo prompt (decisão de produto) |
| Filtros pós-extração descartam oferta boa | Logs `category_scraping_summary` mostram exatamente quantos foram descartados por regra — operador ajusta a config |
| `category_hint` errado contamina classifier | Hint vem de URL específica da categoria — risco baixo. Se houver falso positivo, ajustar URL na config |

## Próximas sprints (impacto)

- **Sprint 6** — `Category.exposure_quota_pct` controla cota na **publicação**; aqui aplicamos cota na **captura**. As duas camadas se complementam.
- **Sprint 7** — Feedback loop pode reescrever `cycle_limit` e `min_discount` por categoria com base em cliques/conversões reais.
