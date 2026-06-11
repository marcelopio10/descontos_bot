# Sprint 6 — Controle de Exposição por Categoria

## Resumo

O selector passa a respeitar uma cota por categoria em cada ciclo de publicação, evitando que uma categoria domine os canais. A cota vem de `Category.exposure_quota_pct` (já seedada na Sprint 1). Decisão R8 da brainstorm: cota **por ciclo**, não por dia — funciona mesmo em volume baixo, sem janela temporal a manter.

Implementado em duas passadas:

1. **1ª passada (quota):** preenche cada categoria com quota até o seu limite, na ordem do score.
2. **2ª passada (overflow):** se sobrar slot do `global_limit`, completa com qualquer oferta — inclusive categorias sem quota e overflow das categorias quentes.

Adicionalmente: **dedup por prefixo do título normalizado** evita que duas variações do mesmo produto entrem no mesmo ciclo.

Flag `exposure_quota_enabled` default `0`. Sprint chega desligada — operador liga via Setting quando confortável.

## Cotas iniciais (decisão de produto, prompt)

| Categoria | Cota | Notas |
|---|---:|---|
| Casa e Cozinha | 30% | maior fatia — categoria âncora |
| Moda Feminina | 15% | divisão Moda 25% (fem) |
| Infantil | 15% | público familiar 35+ |
| Tecnologia Cotidiana | 15% | acessórios, gadgets |
| Moda Masculina | 10% | divisão Moda 25% (masc) |
| Beleza e Cuidados Pessoais | 10% | |
| Saúde e Suplementação | **5%** | exposição limitada — viés do dono |
| Pet / Bebidas / Automotivo / Outros / Ferramentas / Construção / Industrial | 0% | só entram na 2ª passada |

Soma das cotas: **100%**. Já no banco desde a Sprint 1 (`apps/offers/migrations/0005_seed_categories.py`).

Conversão para slots absolutos (em `_resolve_category_quotas`):

```python
slots = ceil(global_limit * pct / 100)
```

Para `global_limit=20`, distribui exatamente 20 slots:

```
casa_cozinha            6 slots
moda_feminina           3 slots
infantil                3 slots
tecnologia_cotidiana    3 slots
moda_masculina          2 slots
beleza_cuidados         2 slots
saude_suplementacao     1 slot
```

## Algoritmo

```
1. Pool de candidatos ordenado por (priority_score, score, discount, price).
2. Calcula quotas absolutas por categoria (1ª vez).
3. Inicializa contadores por marketplace, por categoria e set de prefixos vistos.
4. Passada 1 (respeita quota):
   - Para cada offer:
     - Skip se já selecionada
     - Skip se prefixo do título normalizado já visto
     - Skip se marketplace cheio
     - Skip se categoria não tem quota OU já atingiu a quota
     - Seleciona; loga pass=quota
5. Passada 2 (overflow):
   - Idem, sem checar quota (mantém marketplace_limit + dedup)
   - Loga pass=overflow
6. Loga selector_summary com quotas vs realizado.
```

Tudo na função `select_offers_for_channel`, sem mudar o queryset elegível.

## Prevenção de repetição

Set `seen_prefixes` armazena os primeiros 50 caracteres do `normalized_title` de cada oferta selecionada. Oferta cujo prefixo já está no set é descartada com:

```
selector_drop offer_id=<id> reason=similar_title prefix=<...>
```

Dedup por prefixo é simples e efetivo para variações como "Tênis Adidas Adizero Drive Cor X" vs "Tênis Adidas Adizero Drive Cor Y" — ambos compartilham os primeiros 50 chars normalizados.

## Configuração

| Chave | Onde | Como |
|---|---|---|
| `exposure_quota_enabled` | `apps.panel.Setting` | `'1'` liga, `'0'` desliga |
| Cota por categoria | `Category.exposure_quota_pct` (admin) | Decimal 0..100, `null` = sem quota (só overflow) |

Cota nova ou ajuste:

```python
from apps.offers.models import Category
Category.objects.filter(code='pet').update(exposure_quota_pct=5)
```

Quotas são lidas a cada ciclo — sem cache.

## Relatório

```bash
python3 manage.py composicao_publicacao --days 7
python3 manage.py composicao_publicacao --days 1 --channel telegram_main
```

Saída:
- Composição global por categoria (envios, %real, %cota, delta).
- Composição por canal (top categorias com %).

`delta` é `%real - %cota` em pontos percentuais. Operador usa para validar se a Sprint 6 está convergindo.

Fotografia pré-ativação (7d, `telegram_main`):

| Categoria | Envios | %real | %cota | Delta |
|---|---:|---:|---:|---|
| outros | 363 | 57.3% | — | — |
| casa_cozinha | 81 | 12.8% | 30% | **−17pp** |
| moda_masculina | 41 | 6.5% | 10% | −3.5pp |
| saude_suplementacao | 27 | 4.3% | 5% | −0.7pp |
| ...                | ... | ... | ... | ... |

Cenário evidencia o problema que a Sprint 6 resolve: 57% caem em `outros` enquanto categorias âncora ficam muito abaixo da cota.

## Componentes implementados

| Arquivo | Função |
|---|---|
| `apps/curation/services/selector.py` | quota em 2 passadas, dedup, log de drop por motivo, `_resolve_category_quotas` |
| `apps/curation/management/commands/composicao_publicacao.py` (novo) | relatório global + por canal |
| `apps/panel/management/commands/seed_settings.py` | chave `exposure_quota_enabled` |

## Critérios de aceite (verificados)

- [x] Sistema respeita distribuição configurada (algoritmo em 2 passadas; smoke confirmou alocação 20/20 para global_limit=20).
- [x] Relatório mostra composição por categoria (`composicao_publicacao`).
- [x] Suplementos com cota fixa de 5% e marcação test_controlled (Sprint 1).
- [x] Categorias sem quota não monopolizam — só entram em overflow.
- [x] Limite por marketplace continua respeitado (interage com quota).
- [x] Dedup por prefixo do título funciona com log de motivo.
- [x] Sem cota, comportamento atual preservado (flag off).
- [x] `manage.py check` sem erros. `makemigrations --dry-run` = `No changes detected`.

## Ligando em produção

Sprint 6 chega desligada. Para ativar:

```python
from apps.panel.models import Setting
Setting.objects.update_or_create(
    key='exposure_quota_enabled',
    defaults={'value': '1'},
)
```

Próximo ciclo passa a respeitar cotas. Rodar `composicao_publicacao --days 1` depois para validar convergência.

## Rollback

### Runtime

```python
Setting.objects.filter(key='exposure_quota_enabled').update(value='0')
```

Volta ao algoritmo flat (sem quota). Sem perda — quotas continuam no banco para uso futuro.

### Ajuste pontual de quota

```python
# zerar cota de uma categoria (só entra em overflow)
from apps.offers.models import Category
Category.objects.filter(code='saude_suplementacao').update(exposure_quota_pct=None)
```

### Código

`git revert` é seguro. Sem schema novo nesta sprint.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Cota de uma categoria quente vazia (sem candidatos elegíveis) deixa slot ocioso | 2ª passada (overflow) preenche com qualquer categoria. Garantido |
| `global_limit` baixo (ex: 5) cria distribuição muito enviesada | `_resolve_category_quotas` usa `ceil` — categoria de 5% ainda ganha 1 slot mínimo |
| Dedup por prefixo bloqueia produtos legítimos com nomes similares | Prefixo de 50 chars normalizado tende a diferenciar; se virar problema, ajustar `SIMILAR_TITLE_PREFIX` |
| Cotas somam ≠ 100% | Algoritmo usa cota individual — não exige soma 100; overflow lida com sobra/falta |
| Mudança de quota não reflete imediatamente | Quotas são lidas a cada ciclo, sem cache |

## Próximas sprints (impacto)

- **Sprint 7** — Feedback loop pode ajustar `Category.exposure_quota_pct` automaticamente com base em cliques/conversões (ex: subir cota de categorias que convertem, baixar das que só geram impressão).
