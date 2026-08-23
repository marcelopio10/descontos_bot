# Ingestão do painel de afiliados do ML e recalibragem dos tetos de preço (2026-08-23)

> Origem: até aqui o único dado de receita entrava à mão — o dono copiava JSON do
> DevTools e subia pelo Admin (`docs/AFFILIATE_REPORTS_INGESTION.md`). O
> relatório disponível é **agregado por produto no período**, o que não permite
> separar comissão aprovada de rejeitada nem identificar compra da própria casa.
> Sem isso, os tetos de `max_price` da coleta continuavam sendo intuição sobre
> "preço que o público paga", nunca taxa de comissão medida.

Duas entregas encadeadas: a rotina que traz a venda a venda, e a recalibragem dos
tetos que os 74 primeiros registros permitiram fazer.

---

## Parte 1 — A rotina de ingestão

### Endpoint

Descoberto pelo dono capturando a chamada XHR do próprio painel:

```
GET https://www.mercadolivre.com.br/affiliate-program/api/dashboard/sales/general
    ?filter_time_range=<ISO_INICIO>--<ISO_FIM>
    &items_per_page=50&page=1&order_by=ord_date_created&sort=desc&type=GENERAL
```

Autentica com o **mesmo `ML_COOKIE`** que o scraper já mantém no `.env` — é por
isso que esta rotina pôde virar timer, diferente dos `ingest_affiliate_*`, que
dependem de o dono colar payload. A contrapartida: cookie vencido derruba a
ingestão e a coleta de ofertas juntas, e o cliente emite alerta de operador
(`categoria='ml_cookie_expirado'`) antes de levantar `MLAffiliateAuthError`.

Limites verificados na sondagem do dia:

| Sondagem | Resultado |
|---|---|
| `items_per_page=50` | funciona |
| `items_per_page=100` | página vazia — o teto é 50 |
| `type=<qualquer valor>` | ignorado, sempre cai em `GENERAL` |
| `type=SUBID`, `/sales/subid`, `/clicks`, `/metrics` | 404 ou mesmo `GENERAL` |

**Consequência que importa para o produto:** não existe recorte por SubID. O
`matt_word` que injetamos em todo link **não volta pelo painel**. A atribuição
por canal (WhatsApp × Telegram) continua sem fonte oficial e segue dependendo de
correlação temporal, como registrado na restrição (3) do laudo.

### Peças

| Arquivo | Papel |
|---|---|
| `apps/analytics/services/ml_affiliate_sales_client.py` | Fala com o endpoint, pagina e normaliza em `SaleRecord` |
| `apps/analytics/services/affiliate_parsers/mercadolivre_sales.py` | Persiste, resolve oferta e marca compra própria |
| `apps/analytics/models.py` → `MLAffiliateSale`, `OwnPurchaseSource` | Modelo, migration `0005_mlaffiliatesale` |
| `apps/analytics/management/commands/ingest_ml_affiliate_sales.py` | Comando |
| `apps/analytics/admin.py` | Listagem, filtros e marcação manual de compra própria |
| `apps/analytics/tests/test_ml_affiliate_sales.py` | 16 testes |
| `scripts/ingest-ml-afiliados.{service,timer}` | Automação |

### Por que um modelo novo em vez de `AffiliateConversion`

Granularidade diferente, e as unique constraints do agregado
(`(oferta|ref, fonte, período)`) não comportam venda individual.
`AffiliateConversion` continua sendo a base do `affiliate-summary.json`; uma
coisa não substitui a outra.

**Fora de escopo de propósito:** alimentar `AffiliateConversion` a partir daqui.
Os dois caminhos contariam a mesma venda duas vezes se o relatório agregado do
mesmo período também fosse importado. Unificar é decisão de produto.

### As três regras da rotina

1. **Idempotência por `sale_id`.** Reimportar a mesma janela atualiza o que mudou
   e não duplica linha. É o que permite janela sobreposta.
2. **A janela é larga de propósito (45 dias).** Venda entra como `IN_REVIEW` e só
   resolve para `APPROVED`/`REJECTED` semanas depois — reler o passado recente é
   o que mantém o status correto.
3. **Marcação manual de compra própria manda.** A ingestão nunca sobrescreve o
   que foi marcado no Admin. O automático só age sobre linha ainda não marcada.

### Compra própria: o que o campo significa hoje

O automático usa uma única regra, confirmada pelo dono: venda `REJECTED` é compra
da casa, porque o ML não paga comissão ao afiliado que compra pelo próprio link.
Marca com `own_purchase_source='auto_rejected'`.

**É inferência, não sinal independente.** Na carga inicial, as 8 vendas marcadas
como compra própria são exatamente as 8 `REJECTED`. Compra da casa ainda
`IN_REVIEW` não é detectada — na amostra de maio havia 5 suplementos nessa
situação. Para esses, a marcação no Admin (`manual`) é o caminho.

### Resolução venda → oferta

Casamento por MLB do link quando existe, e por título via Jaccard com limiar
**0,7** (mínimo de 4 tokens, janela de 120 dias para trás) quando não existe.
Limiar alto porque ligar venda à oferta errada é pior do que não ligar. Link de
catálogo (`/p/MLB…`) fica com `external_ref` vazio — é outro namespace.

### Operação

```bash
manage.py ingest_ml_affiliate_sales --days 45              # janela do timer
manage.py ingest_ml_affiliate_sales --since 2026-05-01 --until 2026-08-24
manage.py ingest_ml_affiliate_sales --days 7 --dry-run     # sem persistir
manage.py ingest_ml_affiliate_sales --from-file <json>     # backfill sem chamar o ML
```

Instalação (já feita, `systemd --user`):

```bash
systemctl --user daemon-reload
systemctl --user enable --now ingest-ml-afiliados.timer
```

Verificação:

```bash
systemctl --user list-timers ingest-ml-afiliados.timer
tail -n 50 logs/ingest-ml-afiliados.log
```

Rollback: `systemctl --user disable --now ingest-ml-afiliados.timer`. Nenhum dado
já ingerido é afetado.

**Cadência: semanal, segunda 06:20** (`RandomizedDelaySec=15min`,
`Persistent=true`). Semanal e não diária porque o dado do outro lado muda devagar
e cada execução é requisição autenticada com o cookie da conta — não é chamada
barata como um SELECT local. Duas páginas cobrem 45 dias com folga.

### Carga inicial (lote #7, 2026-08-23 09:21, exit 0)

74 vendas, de 01/05 a 10/08:

| Status | Vendas | Comissão |
|---|---|---|
| `IN_REVIEW` | 47 | R$ 726,34 |
| `APPROVED` | 12 | R$ 121,45 |
| `REJECTED` | 8 | R$ 87,69 |
| `CANCELED` | 7 | R$ 13,73 |

43 das 74 casaram com uma `Offer` nossa; 8 marcadas como compra própria (todas
`REJECTED`, via `auto_rejected`).

Note que **a maior parte da comissão do período ainda está em revisão** — leitura
de receita feita hoje sobre esta base é provisória por construção, e é
exatamente por isso que o timer relê a janela.

---

## Parte 2 — Recalibragem dos `max_price`

Com a taxa de comissão por categoria finalmente medida (74 vendas, mai–ago), os
tetos de `scrapers/category_targets.py` deixaram de ser intuição de preço e
passaram a seguir o que cada categoria **paga**. O gatilho foi o achado de que
45,3% da comissão de cliente de maio veio de vendas acima de R$ 500, e que essa
faixa zerou a partir de junho.

Taxa observada:

- **Alta (12–26%):** perfumaria/beleza 16–17% · moda 16–26% · cozinha 17% ·
  fitness/musculação 16% · equipamento médico 12%
- **Baixa (2,5–7%):** celulares 5% · áudio 5% · acessórios 5% · relógios 6% ·
  pequenos eletrodomésticos 6,8% · colecionáveis 6%

Efeito dos tetos antigos sobre o preço máximo de oferta de ML coletada
(maio → agosto), que mostra quais estavam mordendo:

```
beleza_cuidados       R$ 819  → R$ 299   (teto 300 — cortou o perfume de R$ 717
                                          que rendeu R$ 94,16 a 16% em maio)
infantil              R$ 1549 → R$ 399   (teto 400)
casa_cozinha          R$ 5299 → R$ 642   (teto 600)
tecnologia_cotidiana  R$ 3899 → R$ 2099  (teto 700, vaza por alvo sem hint)
```

Resultado — **a mudança é assimétrica de propósito**: sobe onde a comissão paga,
desce onde não paga.

| Categoria | Antes → Depois | Razão |
|---|---|---|
| `beleza_cuidados` | 300 → 800 | o teto mais danoso do arquivo; perfumaria paga 16% com ticket de R$ 416 |
| `beleza` (outros alvos) | 400 → 800 | mesma razão |
| `casa_cozinha` | 600 → 800 | cozinha paga 16,8%; o teto mordia forte |
| `moda` / `calcados` / `esportes` | 500 → 600 | moda paga 16–26% |
| `infantil` | 400 → 500 | brinquedo paga 11–16% (colecionável, só 6%) |
| `tecnologia_cotidiana` | 800 → 500 | era o teto mais alto do arquivo servindo a 2,5–6,8% |
| `celulares` | 700 → 500 | 5% num ticket de R$ 637 — a pior relação do arquivo |
| `saude_suplementacao` | **intocado** | o teto baixo ali não é comercial: é exposição limitada por viés do dono (~80% das vendas de suplemento registradas são compra dele) |

### Duas armadilhas registradas no arquivo

1. **Alvos com `trust_hint=False` não passam por este filtro.** No ML, `MLB1430`
   e `MLB1276`: sem `category_hint` no payload, `_apply_category_filters` deixa
   passar. Bicicleta ergométrica e o resto de Esportes entram por ali,
   classificados como `outros`, sem teto nenhum. Quem for medir o efeito da
   recalibragem precisa saber disso, senão atribui ao teto um número que veio de
   fora dele.
2. **`CATEGORY_TARGETS` é lido em tempo de import** (`apps/scraping/services/adapters.py:12`),
   e a coleta acontece dentro do processo `run_bot`. Mudar o arquivo não muda
   nada até reiniciar o `run-bot.service` — feito em 2026-08-23 14:42 com
   autorização do dono.

### Como medir se funcionou

O sinal esperado é o preço máximo e o mix de categoria da oferta de ML coletada,
não o volume total. Comparar as próximas semanas com a linha de base de agosto
acima, lembrando de excluir os alvos sem `trust_hint` da conta.

---

## Em aberto

- **Compra própria `IN_REVIEW` não é detectada.** Depende de marcação manual no
  Admin enquanto não houver sinal melhor que o status.
- **Sem atribuição por canal.** O painel não devolve SubID; segue valendo
  correlação temporal.
- **Comissão do período majoritariamente em revisão** (47 de 74). A leitura
  estabiliza nas próximas execuções do timer.
