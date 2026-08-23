# Diversidade de curadoria — fim da "impressão de repetição" (2026-08-21)

> Origem: o dono reportou que as ofertas melhoraram, mas o canal passou a dar
> **impressão de repetição** — dois pares concretos no mesmo dia, duas piscinas
> infláveis e dois power banks de 20000 mAh. Nenhum dos pares era o mesmo
> anúncio, o que é exatamente o que tornava o problema invisível para os gates
> que existiam.

---

## Evidência (banco de produção, `whatsapp_principal`, 2026-08-14 a 2026-08-21)

| Métrica | Valor |
|---|---|
| Envios na janela | 222 |
| Envios com outro da **mesma família** nas 24h anteriores | **63 (28%)** |
| Envios com outro da mesma família nas 6h anteriores | 45 (20%) |
| Tênis | **26 de 222 (12%)** |
| Ofertas coletadas na janela | 386 |
| Tênis entre as coletadas | **52 (13%)** |

Os quatro anúncios reportados:

| offer_id | título | `produto_canonico_id` | enviado |
|---|---|---|---|
| 11389 | Power Bank Hardline 20000mAh | `mercadolivre:MLB65588451` | 20/08 11:44 |
| 11462 | Carregador Portátil Power Bank Turbo 20000mah | `mercadolivre:MLB54026101` | 20/08 18:53 |
| 11485 | Piscina Retangular Inflável Pvc | `mercadolivre:MLB_PiscinaRetangularI` | 20/08 22:41 |
| 11496 | Piscina Infantil Retangular Inflável | `mercadolivre:MLB_PiscinaInfantilRet` | 21/08 02:12 |

Canônicos diferentes em todos os pares → nenhum gate disparou.

---

## Causa raiz — três camadas, não uma

### 1. Coleta: o plano de busca era estruturalmente um plano de tênis

`apps/marketplaces/services/search_query_planner.py` montava o termo de produto
fixo por família de marca:

```python
text = f'{term} {"tênis" if family == "moda" else "oferta" if family else "produto"}'
```

`SEARCH_BRANDS['moda']` tem 12 marcas. Toda marca de moda virava a query
`"<marca> tênis"` — 12 das ~15 queries de marca por marketplace pediam o mesmo
produto. Daí os 13% de tênis no pool coletado.

**Nenhum gate de curadoria conserta um pool enviesado: ele só reduz volume.**

### 2. Curadoria: o dedup era de identidade, não de similaridade

O único dedup era por `produto_canonico_id`, que para Mercado Livre é o **ID do
anúncio** (ver `apps/offers/services/normalizer.build_produto_canonico_id`).
Dois anúncios do mesmo tipo de produto nunca colidiam. O selector legado tinha
um gate de título por Jaccard (`SIMILAR_TITLE_JACCARD_THRESHOLD = 0.75`), mas:
está no caminho legado (opt-out desde 2026-07-05), roda só dentro de uma
seleção, e 0.75 não pega os pares reais (as duas piscinas dão ~0.35).

### 3. Recorrência: o cooldown usava a mesma chave de identidade

`recurrence.normalize_family_key` retorna `canonical:<produto_canonico_id>`
quando existe. Com canônicos distintos, as 72h de cooldown nunca se aplicavam
ao par.

---

## O que mudou

### `apps/curation/services/product_family.py` (novo)

`product_family_key(title)` → tipo de produto (`tenis`, `power_bank`,
`jogo_de_panelas`). Chave de **similaridade**, deliberadamente separada de
`produto_canonico_id`:

- `produto_canonico_id` é identidade e serve para **descartar** duplicata —
  errar funde produtos e perde oferta, por isso continua conservadora.
- `product_family_key` serve só para **espaçar** publicação — errar, no pior
  caso, adia uma oferta algumas horas.

Regras: casa tipo de produto nas 6 primeiras palavras (posição vence
comprimento, para "Cadeira De Praia … piscina" não virar `piscina`); cabeça
genérica antes do tipo marca acessório ("Suporte Para Celular" → `suporte_celular`,
não `celular`); `TYPE_ALIASES` une sinônimos ("carregador portátil" = "power bank");
fallback por palavra-cabeça cobre a cauda longa; título ilegível retorna `''`
(= sem restrição, nunca uma família coletiva).

Validado contra os 222 envios reais: 140 famílias, zero título sem classificação.

### Gates aplicados

| Camada | Arquivo | Regra |
|---|---|---|
| Coleta | `search_query_planner.py` | `FAMILY_PRODUCT_TERMS` rotaciona o produto por índice da marca na família (determinístico, sem `random`) |
| Pool | `prepare_ai_curation_batch.py` | `CANDIDATE_MAX_PER_FAMILY = 2` no payload do agente |
| Histórico | `recurrence.py` | cooldown de família + teto de envios por janela, por canal |
| Lote | `batch_optimizer.py` | `max_per_family=1`; categoria limitada a 50% do lote |
| Agente | `ai_prompt.py` / `hermes_runner.py` | `product_family` por oferta, `recent_families` do canal e instrução explícita de diversidade |

### Settings (`apps.panel.models.Setting`, sem migração)

| Chave | Default | Efeito |
|---|---|---|
| `offer_family_spacing_enabled` | `true` | desliga todo o espaçamento temporal |
| `offer_family_cooldown_hours` | `8` | intervalo mínimo entre duas ofertas da mesma família |
| `offer_family_window_hours` | `24` | janela de contagem |
| `offer_family_max_window_sends` | `2` | teto de envios da família na janela |

Rollback: `offer_family_spacing_enabled=false` desarma o gate temporal;
`max_per_family=0` e `max_category_share=0` desarmam o gate de lote.

---

## Impacto esperado no volume

Simulação sobre a série real de 7 dias, **assumindo o pior caso** (nenhuma
substituição — cada bloqueio vira um envio a menos):

| Política | Envios/7d | Δ |
|---|---|---|
| Hoje | 222 | — |
| cooldown 8h + máx 2/24h (**escolhida**) | 176 | −21% |
| cooldown 6h + máx 3/24h | 181 | −18% |
| cooldown 24h + máx 1/24h | 165 | −26% |

O número real deve ser melhor que −21%, porque a correção de coleta amplia o
pool: hoje entram 40–60 ofertas novas/dia contra ~40 envios/dia, ou seja, o
sistema publica quase tudo que coleta e tem pouca margem para trocar.
**Se o volume cair mais que o previsto, o gargalo é coleta, não o gate.**

---

## Verificação

```bash
python manage.py test apps.curation apps.marketplaces
python manage.py check && python manage.py makemigrations --dry-run --check
python scripts/amazon_compliance_check.py

# dry-run contra o banco real (modo dry_run nunca é consumido pela entrega,
# que só aceita homolog/production)
python manage.py prepare_ai_curation_batch --channel whatsapp_principal \
  --mode dry_run --dry-run --runner mock --candidate-limit 50 --skip-images
```

Resultado do dry-run em 2026-08-21: lote de 18 itens, **18 famílias distintas,
zero repetição**.

Falhas pré-existentes na suíte (também falham sem estas mudanças, causadas por
`SHOPEE_AFFILIATE_ENABLED=true` no `.env` local): 2 em
`apps.marketplaces.tests.test_radar_mercado`, 2 em
`apps.analytics.tests.test_link_builder_shopee`.

---

## Correção do mesmo dia — o selector legado não tinha gate nenhum

Medido algumas horas depois de ativar: dos 25 envios pós-restart, **17 saíram
pelo selector legado**, que não passa por nenhum dos gates acima. Entre eles, 7
fones de ouvido em 3 minutos.

Os gates nasceram todos dentro do fluxo de curadoria IA, e o selector legado é o
**fallback de quando a IA falha** — ou seja, roda justamente quando algo já deu
errado. Naquele ciclo, a cadeia foi: agente devolveu 16 de 50 decisões sem
`rewritten_caption_whatsapp` (lote inteiro rejeitado na validação) → fallback IA
caiu por autenticação expirada do profile Hermes `descontos-bot` → "Nenhum lote
curado pronto" → selector legado → 17 envios sem espaçamento.

Comparação no mesmo período, que mostra que os gates funcionam onde existem:

| Caminho | Envios | Famílias | Em família repetida |
|---|---|---|---|
| Curadoria IA (com gates) | 8 | 8 | **0 (0%)** |
| Selector legado (sem gates) | 17 | 11 | 8 (47%) |

O que mudou em `apps/curation/services/selector.py`:

1. `filter_saturated_families` passou a rodar logo depois de
   `filter_blocked_recurrence` — o mesmo espaçamento por histórico do outro
   caminho.
2. Teto de **1 por família dentro da própria seleção** (`MAX_PER_FAMILY`),
   equivalente ao `max_per_family` do `batch_optimizer`. O filtro de histórico
   sozinho não resolveria: os envios do ciclo corrente ainda não estão no banco
   quando a seleção é montada, então os 7 fones sairiam juntos de qualquer jeito.

O gate de título que já existia (prefixo de 50 caracteres + Jaccard 0,75) não
pegava nada disso: "PHILIPS, Fone de Ouvido com Microfone TAUE101WT" e "JBL, Fone
de Ouvido Bluetooth Over-Ear Tune 530BT" compartilham poucos tokens.

## Limitações conhecidas

- A família é heurística de texto. Falso positivo adia uma oferta; falso
  negativo deixa passar uma repetição. Nenhum dos dois apaga ou funde registro.
- `PRODUCT_TYPES` é incompleta de propósito. Só entra tipo novo quando o
  fallback separar indevidamente duas grafias do mesmo produto.
- O espaçamento é **por canal**. WhatsApp e Telegram contam separado — é o
  comportamento correto, mas significa que a mesma oferta segue saindo nos dois.
- A rotação de produto por marca não sabe o que a marca fabrica ("lupo
  bermuda" é plausível, "lupo jaqueta" nem tanto). O scraper simplesmente traz
  menos resultados nesses casos; não há efeito de qualidade.
