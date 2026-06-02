# Ingestão de relatórios de afiliados

Documento operacional. Como subir, para o Admin, os relatórios oficiais de
Amazon Associates e Mercado Livre Afiliados que alimentam o `/dashboard`.

Decidido após o tracking customizado ser abortado na Sprint 2 (ver `GROWTH_PLAN_DESCONTOS_BOT.md` §9).
Fonte de verdade agora é o relatório do próprio marketplace — não tem mais
estimativa de cliques via Vercel KV.

---

## Cadência sugerida

Importar **toda segunda-feira de manhã** a janela da semana anterior (segunda
a domingo). O dashboard sempre mostra os últimos 7 dias agregados.

Re-importar período já carregado **não duplica**: o parser usa
`update_or_create(offer × canal × fonte × dia)` e sobrescreve com os números
mais recentes. Útil quando a Amazon ajusta comissão depois do fechamento.

---

## Amazon Associates

### 1. Exportar do painel

1. Entrar em [associados.amazon.com.br](https://associados.amazon.com.br/).
2. Menu superior **Relatórios → Visão geral de ganhos** (ou "Earnings Report").
3. Selecionar o período (ex.: semana anterior).
4. Escolher o agrupamento por **Data + ASIN** (granularidade obrigatória).
5. Clicar **Baixar relatório** → `.tsv` (Tab-delimited UTF-8).

> O parser também aceita CSV separado por `,` ou `;`, mas o default Amazon é TSV.

### 2. Importar pelo Admin

1. Admin → **Analytics → Lotes de importação de afiliados** → botão
   **Importar Amazon Associates**.
2. Selecionar o arquivo baixado.
3. **Importar**. Mensagens flash mostram quantas linhas foram importadas, quantas
   ignoradas e qualquer warning (ASINs órfãos, Tracking IDs divergentes).
4. `affiliate-summary.json` é regerado automaticamente ao final.

### 3. Alternativa via CLI

```bash
python manage.py ingest_affiliate_amazon --file /caminho/relatorio.tsv --dry-run
python manage.py ingest_affiliate_amazon --file /caminho/relatorio.tsv
```

`--dry-run` roda o parser sem persistir nada — útil para conferir contagem
antes de aceitar.

### Observações importantes

- **Sem canal:** o Earnings Report da Amazon não traz a origem do clique
  (canal social). Toda conversão fica com `social_channel = null`.
- **ASIN é a chave:** o parser resolve `Offer` por `marketplace='amazon'` +
  `asin`. ASINs órfãos viram warning no batch e não bloqueiam a importação.
- **Tracking ID:** se aparecer um Tracking ID diferente do
  `Marketplace.affiliate_tag` cadastrado, gera warning para auditoria.

---

## Mercado Livre Afiliados

**Não existe export oficial** (confirmado por pesquisa em 2026-06). O painel
ML só mostra os dados em tela. Solução: capturar o JSON da response interna
no DevTools do navegador e colar no Admin.

### 1. Capturar o JSON

1. Entrar em [mercadolivre.com.br/afiliados](https://www.mercadolivre.com.br/afiliados/).
2. Abrir a página do relatório de SubID / Marketing Toolbox.
3. **Abrir DevTools** (F12) → aba **Network** → filtrar por `XHR/Fetch`.
4. Selecionar o período desejado no painel — observar a request que dispara.
5. Clicar na request, aba **Response** → **copiar** (ou "Copy response").

> O schema do JSON pode mudar com o tempo. O parser é defensivo: aceita
> chaves alternativas (`matt_word`/`subid`, `clicks`/`cliques`,
> `commission`/`commission_amount`, etc.). Se um item falhar, ele é contado
> em `rows_skipped` com warning explicando a linha bruta.

### 2. Importar pelo Admin

1. Admin → **Lotes de importação** → **Importar Mercado Livre**.
2. Colar o JSON na textarea **OU** anexar um arquivo `.json`.
3. **Importar**.

### 3. Alternativa via CLI

```bash
# de arquivo
python manage.py ingest_affiliate_mercadolivre --file /tmp/painel-ml.json

# colando direto (Ctrl-D pra finalizar)
python manage.py ingest_affiliate_mercadolivre --stdin
```

### Como o SubID resolve canal + oferta

O `link_builder.py` propaga em todo link ML o SubID no formato
**`dbot_<canal_curto>_<offer_id>`** (ex.: `dbot_tg_homolog_1234`).

O parser:

1. Casa a regex `^dbot_(?P<channel>[a-z0-9_]+)_(?P<offer_id>\d+)$`.
2. Resolve `Offer` por `id` + marketplace ML.
3. Resolve `SocialChannel` pelo `channel_codes.expand_short_channel_code()`:
   - `wa_main` → tenta `whatsapp_main`, `whatsapp_channel_main`, `whatsapp_group_main`.
   - `tg_homolog` → tenta `telegram_homolog`, `telegram_channel_homolog`.
   - Empate: prefere canal `is_enabled=True`.

Items com SubID fora do padrão (cliques orgânicos no link sem segmentação)
viram conversão com `social_channel=null` e `subid` contendo o valor bruto.

---

## Republicar dashboard sem importar nada

```bash
python manage.py publish_affiliate_summary
python manage.py publish_affiliate_summary --window-days 30
```

Regera `site/affiliate-summary.json` a partir das conversões já no banco. Útil
para mudar a janela mostrada no dashboard sem reprocessar arquivos.

---

## Anti-checklist

- ❌ Não tentar reativar `site/api/click.js` / `clicks.js` — abortados na
  Sprint 2, mantidos parados por decisão de produto.
- ❌ Não credencializar painel ML no servidor (Playwright headless) — solução
  rejeitada por exigir 2FA e ser frágil a mudanças de DOM.
- ❌ Não persistir o payload bruto em banco; só o `payload_sha256` para
  dedup defensivo de re-upload idêntico.

---

## Riscos abertos

- **Schema do XHR ML**: estimado. Primeira importação real pode precisar de
  ajuste no parser (chaves novas). Reportar via warning do batch.
- **Tracking ID Amazon**: a presença da coluna varia conforme tipo de
  relatório. Sem ela, `subid` fica vazio no batch Amazon — sem prejuízo
  (canal já é null na Amazon).
