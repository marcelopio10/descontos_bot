# Ingestão de relatórios de afiliados

Documento operacional. Como subir, para o Admin, os relatórios oficiais de
Amazon Associates e Mercado Livre Afiliados que alimentam o `/dashboard`.

Decidido após o tracking customizado ser abortado na Sprint 2 (ver `GROWTH_PLAN_DESCONTOS_BOT.md` §9).
Fonte de verdade agora é o relatório do próprio marketplace — não tem mais
estimativa de cliques via Vercel KV.

---

## Modelo de dados

`AffiliateConversion` agrega:

- `offer` (FK opcional, SET_NULL) — preenche quando ASIN/MLB casa com nosso catálogo.
- `external_ref` — ASIN da Amazon ou MLB do ML quando a oferta **não** está no catálogo.
- `product_title` — título do produto vindo do relatório (fallback quando órfã).
- `source` — `amazon` ou `mercado_livre`.
- `period_start` + `period_end` — janela coberta pelo relatório.
- `clicks` / `conversions` / `revenue_brl` / `commission_brl`.

**Granularidade**: 1 linha por (oferta OU external_ref) × source × período.

**Sem canal**: nem Amazon (Earnings Report) nem o painel ML expõem origem do
clique por canal social. `social_channel` fica null. Para segmentar por canal
seria necessário rodar relatórios separados por SubID/filtro — não suportado
nesta primeira versão.

---

## Cadência sugerida

Importar **toda segunda-feira de manhã** a janela da semana anterior (segunda
a domingo). O dashboard sempre mostra os últimos 7 dias agregados.

Re-importar período já carregado **não duplica**: o parser usa
`update_or_create((offer | external_ref), source, period_start, period_end)` e
sobrescreve com os números mais recentes. Útil quando a Amazon ajusta comissão
depois do fechamento. Re-importar payload **idêntico** (mesmo SHA-256) é
bloqueado com mensagem amigável apontando o lote anterior.

---

## Amazon Associates

### 1. Exportar relatório por ASIN

> **Importante**: precisa ser o relatório agrupado por **ASIN** (1 linha por
> produto). O relatório por Tracking ID é uma única linha agregada — não
> identifica produto e o parser recusa.

1. Entrar em [associados.amazon.com.br](https://associados.amazon.com.br/).
2. **Relatórios → Ganhos → ASIN** (ou caminho equivalente do painel atual).
3. Selecionar o período (ex.: semana anterior).
4. Clicar **Baixar relatório**.

Colunas esperadas (tolerante a aliases pt-BR/en):

```
ASIN | Produto | Cliques | Produtos pedidos | Produtos enviados |
Receita de produtos enviados | Ganhos totais | (Tracking ID opcional)
```

### 2. Importar pelo Admin

1. Admin → **Lotes de importação de afiliados** → botão **Importar Amazon Associates**.
2. Anexar o arquivo.
3. Preencher **Início do período** e **Fim do período** (Amazon não inclui no arquivo — você precisa informar).
4. **Importar**. Mensagens flash mostram linhas importadas, ignoradas e warnings
   (ASINs órfãos, Tracking IDs divergentes).
5. `affiliate-summary.json` é regerado automaticamente.

### 3. Alternativa via CLI

```bash
python manage.py ingest_affiliate_amazon \
    --file /caminho/relatorio.tsv \
    --period-start 2026-05-26 \
    --period-end 2026-06-01 \
    --dry-run

python manage.py ingest_affiliate_amazon \
    --file /caminho/relatorio.tsv \
    --period-start 2026-05-26 \
    --period-end 2026-06-01
```

`--dry-run` roda o parser sem persistir.

### Observações

- **Sem canal**: `social_channel = null` em toda conversão Amazon.
- **ASIN como chave**: ASINs não cadastrados viram conversões "órfãs"
  (`offer=null`, `external_ref=ASIN`, `product_title` do relatório). Continuam
  agregando no dashboard, marcadas como "não cadastrada".
- **Tracking ID** divergente da `Marketplace.affiliate_tag` gera warning.

---

## Mercado Livre Afiliados

**Não existe export oficial** (confirmado por pesquisa em 2026-06). O painel
ML só mostra os dados em tela. Captura: copiar o JSON da response interna no
DevTools.

> **Existe desde 2026-08-23 um segundo caminho, automático, para o ML** —
> `manage.py ingest_ml_affiliate_sales`, que chama o endpoint do painel com o
> `ML_COOKIE` e roda em timer semanal. Ver
> `docs/INGESTAO_PAINEL_ML_2026-08-23.md`.
>
> Os dois **não se substituem**: o desta seção é o relatório agregado por produto
> no período (`item_list`/`entity_id`) e alimenta `AffiliateConversion` e o
> `affiliate-summary.json`; o novo é venda a venda, com status e compra própria,
> e alimenta `MLAffiliateSale`. Cuidado ao somar: importar o mesmo período pelos
> dois caminhos conta a venda duas vezes se alguém unificar os totais.

### 1. Capturar o JSON

1. Entrar em [mercadolivre.com.br/afiliados](https://www.mercadolivre.com.br/afiliados/).
2. Abrir relatório de performance (item list).
3. **Abrir DevTools** (F12) → aba **Network** → filtrar por `XHR/Fetch`.
4. Selecionar o período no painel — observar a request que dispara.
5. Clicar na request, aba **Response** → **Copy response** (botão direito ou ícone).

Schema validado (campos relevantes):

```json
{
  "item_list": [
    {
      "product": "Nome do produto",
      "entity_id": "MLB...",       // casa com Offer.external_id
      "quantity": 3,                // conversões
      "earnings": 23.34,            // comissão R$
      "total_sales": 142.23,        // receita R$
      "fee": 0.20                   // % comissão (não usado)
    }
  ],
  "filter_time_range": "1777766400000--1780358400000"  // millis UNIX
}
```

### 2. Importar pelo Admin

1. Admin → **Lotes de importação** → **Importar Mercado Livre**.
2. Colar o JSON na textarea **OU** anexar um arquivo `.json`.
3. **Importar**. O período sai automaticamente de `filter_time_range`.

### 3. Alternativa via CLI

```bash
# de arquivo
python manage.py ingest_affiliate_mercadolivre --file /tmp/painel-ml.json

# colando direto (Ctrl-D pra finalizar)
python manage.py ingest_affiliate_mercadolivre --stdin
```

### Observações

- **Sem canal**: `social_channel = null` (ML não expõe origem por SubID no relatório).
- **Sem cliques**: `clicks = 0` (ML só mostra conversões agregadas).
- **Entity IDs órfãos**: `entity_id` que não bate com nenhum `Offer.external_id`
  vira conversão órfã, marcada como "não cadastrada" no dashboard.

---

## Republicar dashboard sem importar nada

```bash
python manage.py publish_affiliate_summary
python manage.py publish_affiliate_summary --window-days 30
```

Regera `site/affiliate-summary.json` a partir das conversões já no banco. Útil
para mudar a janela mostrada no dashboard.

---

## Anti-checklist

- ❌ Não tentar reativar `site/api/click.js` / `clicks.js` — abortados na
  Sprint 2, mantidos parados por decisão de produto.
- ❌ Não credencializar painel ML no servidor (Playwright headless) — solução
  rejeitada por exigir 2FA e ser frágil a mudanças de DOM.
- ❌ Não persistir payload bruto em banco; só `payload_sha256` para dedup.

---

## Riscos abertos

- **Schema XHR do ML pode mudar**: aceita só os campos atuais
  (`item_list`, `entity_id`, `quantity`, `earnings`, `total_sales`,
  `filter_time_range`). Mudança quebra parser — atualizar
  `apps/analytics/services/affiliate_parsers/mercadolivre.py`.
- **Schema TSV da Amazon**: usa aliases tolerantes para colunas pt-BR/en. Se
  cabeçalho mudar substancialmente, adicionar alias em `COLUMN_ALIASES`.
- **Segmentação por canal**: não implementada nesta versão. Se quiser breakdown
  WhatsApp vs Telegram, será necessário (a) rodar relatórios separados por
  SubID no painel ML e adicionar campo no Admin pra informar manualmente o
  canal; ou (b) mudar processo de envio para usar links curtos rastreados.

---

## Shopee Afiliados (ingestão automática — RESTR-04)

Diferente de Amazon e Mercado Livre, o **Shopee Affiliate Program** é a
**única fonte com relatório de conversão exportável oficialmente** pelo
próprio portal (RESTR-04 do laudo). Por isso só a Shopee tem um comando de
ingestão dedicado; ML/Amazon continuam manuais (seções acima).

### ⚠️ Aviso — schema de colunas é melhor estimativa, não validada

Este parser foi escrito **sem acesso a um export real** do painel Shopee
Affiliate. As colunas aceitas (`COLUMN_ALIASES` em
`apps/analytics/services/affiliate_parsers/shopee.py`) são a melhor hipótese
com base na nomenclatura pública do programa (Order ID, Item ID, Shop ID,
Item Name, Click Time, Conversion Time, Status, Sub ID 1-5, Actual
Amount/GMV, Commission). **Na primeira vez que alguém for usar isso com um
arquivo real**: baixe o relatório de conversão do portal, rode com
`--dry-run` e confira o cabeçalho contra `COLUMN_ALIASES` antes de confiar no
resultado. Se algum nome de coluna divergir, adicione o alias correspondente
no dicionário (mesmo padrão tolerante usado no parser da Amazon) — não é
necessário mudar a estrutura do comando.

### 1. Exportar o relatório de conversão

1. Entrar no painel do [Shopee Affiliate Program](https://affiliate.shopee.com.br/)
   (ou `https://affiliate.shopee.com.br/offer/list` dependendo da conta).
2. **Relatórios → Relatório de Conversão** (Conversion Report) — não usar o
   relatório de cliques isolado, que não tem valor de comissão por item.
3. Selecionar o período desejado e exportar em CSV/XLSX (o parser lê
   CSV/TSV; se só houver XLSX, salvar como CSV antes de importar).

Colunas esperadas (tolerante a aliases pt-BR/en — ver aviso acima):

```
Order ID | Item ID | Shop ID | Item Name | Click Time | Conversion Time |
Status | Sub ID 1..5 | Actual Amount | Commission | (Quantity opcional)
```

Só **Item ID** e **Commission** são obrigatórias — as demais são usadas
quando presentes (Shop ID melhora a resolução do produto, ver observações).

### 2. Importar via CLI

```bash
# dry-run primeiro, sempre — confere cabeçalho, período detectado e warnings
python manage.py ingest_affiliate_shopee \
    --file /caminho/relatorio_conversao_shopee.csv \
    --dry-run

# commit
python manage.py ingest_affiliate_shopee \
    --file /caminho/relatorio_conversao_shopee.csv
```

Não existe fluxo Admin dedicado para Shopee nesta versão (só CLI) — o
formulário de upload do Admin cobre hoje apenas Amazon e Mercado Livre.

Período (`period_start`/`period_end`): diferente do Amazon (sempre manual)
e mais parecido com o ML (vem do próprio payload), o comando **tenta
derivar automaticamente** o período do min/max das colunas `Conversion
Time`/`Click Time` presentes no arquivo. Informe manualmente só se o
arquivo não tiver essas colunas ou se quiser forçar uma janela específica:

```bash
python manage.py ingest_affiliate_shopee \
    --file /caminho/relatorio.csv \
    --period-start 2026-07-13 \
    --period-end 2026-07-19
```

Status: por padrão só linhas com status "confirmado"/"confirmed" (ou sem
coluna de status — assume-se que o export já é só de confirmadas) entram na
agregação. Linhas "cancelado"/"inválido" são sempre ignoradas. Use
`--include-pending` para também contar conversões "pendente"/"pending":

```bash
python manage.py ingest_affiliate_shopee --file /caminho/relatorio.csv --include-pending
```

`--dry-run` roda o parser sem persistir. `--no-publish` pula a atualização
automática de `affiliate-summary.json` após a importação.

### Observações

- **Chave de produto**: `Offer.external_id` da Shopee é
  `"{itemId}:{shopId}"` (ver `apps/marketplaces/services/shopee_normalizer.py`).
  Quando o relatório traz Shop ID, o parser casa exato. Quando só traz Item
  ID (comum em exports resumidos), a resolução é **best-effort**: só resolve
  se aquele Item ID for inequívoco entre as ofertas Shopee já cadastradas;
  caso contrário fica marcado como não resolvido (órfão), sem adivinhar.
- **Itens órfãos**: Item IDs sem oferta cadastrada (ou ambíguos por falta de
  Shop ID) viram conversões "órfãs" (`offer=null`, `external_ref` com a
  chave usada), do mesmo jeito que Amazon/ML — continuam agregando no
  dashboard.
- **SubID popula o canal (Sprint 4, Tarefa 4.1)**: o link Shopee gerado por
  `shopee_link_generator.py` grava `subId1=descontosbot`,
  `subId2=canal` (formato curto — `wa_<canal>`/`tg_<canal>`, mesma convenção
  gerada por `_short_channel_code()` em
  `apps/analytics/services/link_builder.py` no momento do envio),
  `subId3=campanha`, `subId4=categoria`, `subId5=lote/data`. O parser lê a
  coluna **Sub ID 2** e reconstrói `AffiliateConversion.social_channel`:
  `wa_` vira `whatsapp_`, `tg_` vira `telegram_`, e o resultado é buscado em
  `SocialChannel.code`. Isso só passa a acontecer de fato quando
  `SHOPEE_AFFILIATE_ENABLED=true` estiver ligado no envio (hoje desligado
  por padrão em produção) — com a flag desligada, os links Shopee enviados
  não carregam SubID de canal e o `subId2` do relatório fica vazio para
  essas conversões. Quando o subId2 está ausente, tem prefixo desconhecido
  (ex. `ig_`/`site` — Instagram e outros canais não mapeados) ou não casa
  com nenhum `SocialChannel` cadastrado, `social_channel` continua `null`
  — degradação aceitável, não erro. O resumo do batch (`AffiliateImportBatch.notes`)
  reporta quantos itens resolveram canal vs não.
- **Idempotência**: mesmo padrão das outras fontes — hash SHA-256 do arquivo
  bloqueia reimportar o payload idêntico; reimportar um período com dados
  diferentes sobrescreve via `update_or_create`.
- **Cancelamento tardio**: a Shopee pode cancelar uma conversão depois do
  fechamento (devolução, fraude). Reimportar o relatório atualizado do
  mesmo período sobrescreve os números — mesmo comportamento do Amazon
  quando ajusta comissão pós-fechamento.
