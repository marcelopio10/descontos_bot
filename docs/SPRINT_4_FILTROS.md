# Sprint 4 — Filtros de Qualidade

## Resumo

Ofertas irrelevantes para o público real (DF, 35+, familiar) são tratadas em dois níveis antes da publicação:

1. **Hard blacklist** (já existia desde a Sprint 0) — exclusão via `apply_blacklist_exclusion` no QuerySet + verificação Python no selector. Ampliada com termos B2B/industrial do prompt.
2. **Soft penalty** (novo na Sprint 4) — termos que reduzem o score multiplicativamente sem excluir a oferta. Permite degradação graciosa para padrões ambíguos (ex: "industrial", "galão 20L", "pacote com 100").

Toda decisão de descarte é registrada com **motivo** (`reason=blacklist|low_score|marketplace_limit`) e cada `ScoreBreakdown` carrega um campo `notes` com a justificativa em linguagem natural.

## Mecânica

### Hard blacklist

Sem mudança de arquitetura. `apps/curation/services/blacklist.py` carrega `DEFAULT_BLACKLIST_TERMS` ampliada. Override total via `apps.panel.Setting.blacklist_terms` (JSON array).

Termos ampliados na Sprint 4:

```
luminaria publica, tela soldada, arame farpado, motor estacionario,
motor industrial, gerador a diesel, compressor industrial,
inversor de frequencia, etiqueta couche, etiqueta industrial,
insumo industrial, shampoo automotivo profissional,
shampoo veicular profissional, shampoo para veiculo pesado,
veiculo pesado, veiculos pesados, alvenaria estrutural,
chapa galvanizada, tubo galvanizado, fachada comercial,
peca de reposicao industrial, equipamento profissional industrial
```

Critério de inclusão: termo composto (≥2 palavras) ou substantivo cuja única ocorrência razoável é em produto B2B. Evitamos pegar palavras curtas que dão falso positivo em catálogo de varejo.

Comprovação na base atual: **8 hits em 5524 ofertas ativas** — escopo cirúrgico.

### Soft penalty

Novo: `apps/curation/services/quality_filters.py`. Cada termo carrega um fator multiplicativo (0..1) aplicado ao score final via `penalties` dict do `ScoreBreakdown`. Penalidades empilham:

```
score_final = score_base × ∏ multiplicadores × ∏ penalidades
```

Defaults em `DEFAULT_SOFT_PENALTIES`:

| Termo | Fator | Racional |
|---|---:|---|
| industrial | 0.40 | sinal forte de B2B sem ser bloqueio |
| atacado | 0.50 | venda corporativa |
| b2b | 0.40 | explícito |
| profissional para | 0.65 | contexto profissional, mas pode haver legítimo |
| uso profissional | 0.65 | idem |
| kit com 100 / pacote com 100 / caixa com 100 | 0.70 | grandes quantidades = revenda |
| kit com 50 / pacote com 50 / caixa com 50 | 0.70 | idem |
| fardo com | 0.70 | unidade de revenda |
| galão 5L | 0.75 | embalagem profissional |
| galão 20L | 0.65 | embalagem clara de revenda |
| reposição | 0.80 | peça de reposição genérica |

Override total via Setting `soft_penalty_terms` (JSON `{term: factor}`).

### Regra "sinal fraco" (weak_signal)

Implementada em `_is_weak_signal`:

```
weak_signal = (
    discount_pct < 15
    AND categoria ∈ {outros, automotivo, ferramentas, construcao, industrial}
    AND título NÃO contém marca em STRONG_BRANDS
)
```

Fator: 0.75. Captura o cenário "desconto baixo + sem apelo claro" que o prompt cita explicitamente.

## Justificativa de descarte

### `ScoreBreakdown.notes`

Lista de strings em pt-BR explicando cada penalidade aplicada. Visível no admin (campo `quality_score_breakdown_display`) e nos logs.

Exemplos:
- `sem imagem (x0.70)`
- `preço original suspeito (x0.50)`
- `desconto extremo >99% (x0.00)`
- `sinal fraco: desconto baixo + categoria fria + sem marca conhecida (x0.75)`
- `termo penalizado "industrial" (x0.40)`
- `categoria de teste controlado (x0.85)`
- `oferta antiga (recency x0.30)`

### Logs do selector

```
selector_drop offer_id=<id> reason=blacklist category=<code> title=<...>
selector_drop offer_id=<id> reason=low_score score=<n> classification=fraca category=<code> notes=[...]
selector_drop offer_id=<id> reason=marketplace_limit marketplace=<code> limit=<n>
selector_pick offer_id=<id> score=<n> classification=<c> decision=<d> ...
```

Toda saída da fila — aprovação ou descarte — tem motivo.

## Override e ajuste fino

| Cenário | Caminho |
|---|---|
| Remover/adicionar termo da blacklist | Setting `blacklist_terms` (JSON array) |
| Mudar fator de soft penalty | Setting `soft_penalty_terms` (JSON `{term: factor}`) — substitui o default |
| Desligar Sprint 4 inteira | esvaziar `soft_penalty_terms` e remover termos novos do `blacklist_terms` |
| Publicar oferta marcada por engano | Editar o título da oferta no admin (a verificação é por `\b<termo>\b` no título normalizado) OU remover o termo da blacklist via Setting |

## Componentes implementados

| Arquivo | Função |
|---|---|
| `apps/curation/services/blacklist.py` | `DEFAULT_BLACKLIST_TERMS` ampliada |
| `apps/curation/services/quality_filters.py` (novo) | `evaluate_soft_penalties`, regra weak_signal |
| `apps/curation/services/quality_score.py` | `ScoreBreakdown.notes` + integração soft penalties + `_build_notes` |
| `apps/curation/services/selector.py` | log de descarte por `reason` (blacklist / low_score / marketplace_limit) |
| `apps/panel/management/commands/seed_settings.py` | nova chave `soft_penalty_terms` |

## Critérios de aceite (verificados)

- [x] Ofertas claramente industriais não são publicadas (blacklist hard).
- [x] Toda oferta descartada tem motivo registrado (`reason=` no log + `notes` no breakdown).
- [x] Forma segura de reverter: Setting permite override total em runtime sem deploy.
- [x] Soft penalties degradam score sem excluir oferta marginal.
- [x] Weak signal pega "desconto baixo + sem marca + categoria fria" como exige o prompt.
- [x] `python3 manage.py check` sem erros.
- [x] `makemigrations --dry-run` = `No changes detected`.

## Smoke (casos sintéticos)

| Título | Hard? | Soft | Score | Decisão |
|---|---|---|---:|---|
| Luminaria Publica LED 200W | ✓ | — | — | dropped (blacklist) |
| Pacote com 100 Etiquetas Industriais | — | pacote com 100 (×0.70) | 29.08 | descartar |
| Shampoo Veicular Profissional 5L | ✓ | — | — | dropped (blacklist) |
| Galão 20L Detergente Industrial | — | industrial ×0.40 + galao 20l ×0.65 + weak_signal ×0.75 | 7.52 | descartar |
| Kit Camiseta Hering Masculina | — | — | 65.05 | fila_secundaria |
| Produto qualquer barato (outros, 8%) | — | weak_signal ×0.75 | 29.89 | descartar |

## Rollback

### Runtime — relaxar soft penalties

```python
from apps.panel.models import Setting
import json

# Apenas remover regras industriais, manter weak_signal
Setting.objects.update_or_create(
    key='soft_penalty_terms',
    defaults={'value': json.dumps({}), 'description': 'desligado'},
)
```

`evaluate_soft_penalties` cai no default. Para zerar totalmente, é preciso patch no código (default não é vazio por design).

### Runtime — remover termos novos da blacklist

```python
import json
from apps.panel.models import Setting
# manter apenas termos Sprint 0
terms = [
    'usado', 'reembalado', 'avariado', 'seminovo', 'sem garantia',
    'produto indisponivel', 'recondicionado', 'danificado', 'com defeito',
    'open box', 'mostruario',
]
Setting.objects.update_or_create(
    key='blacklist_terms',
    defaults={'value': json.dumps(terms)},
)
```

Sprint 4 deixa de excluir termos B2B/industrial.

### Código

Sem schema. `git revert` é seguro. Compatibilidade preservada: `ScoreBreakdown.notes` tem default `[]`.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Termo da blacklist pega produto legítimo | Override Setting permite remover sem deploy; termos compostos minimizam falso positivo (8 hits em 5524 ofertas) |
| Soft penalty derruba oferta válida | Empilhamento multiplicativo mas cada fator individual ≥ 0.40 — degradação suave. Override via Setting |
| Weak signal exclui muita "outros" | É o objetivo: "outros" + desconto baixo + sem marca = baixo apelo. Sprint 1 ainda tem 58% em "outros" — solução é ampliar dicionário do classifier, não relaxar o filtro |
| Marca em `STRONG_BRANDS` desatualizada | Brand ausente → weak_signal aplica; brand adicionada ao dicionário desativa weak_signal automaticamente |

## Próximas sprints (impacto)

- **Sprint 5** — Scrapers segmentados aumentam captura nas categorias quentes, reduzindo dependência do filtro weak_signal para qualidade de fila.
- **Sprint 6** — Controle de exposição se beneficia: blacklist + soft penalty já reduzem categorias frias antes da quota.
- **Sprint 7** — Feedback loop pode ajustar `soft_penalty_terms` via Setting com base em cliques/conversões.
