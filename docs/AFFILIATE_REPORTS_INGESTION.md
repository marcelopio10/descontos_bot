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
