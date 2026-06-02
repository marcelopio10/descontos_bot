# GROWTH PLAN — descontos.bot

> Documento gerado pela Sprint 1: Diagnóstico Técnico e Plano de Execução.
> Base: inspeção do código, análise de 5 agentes especialistas, plano de growth aprovado pelo PO.
> Data: 2026-05-26

---

## 1. Diagnóstico Técnico — Estado Atual

### 1.1 Produto

| Componente | Status | Detalhe |
|---|---|---|
| Apps Django | :white_check_mark: 8 apps | `_base`, `marketplaces`, `offers`, `scraping`, `distribution`, `orchestration`, `panel`, `social_posts` |
| Models | :white_check_mark: 7 modelos | `Marketplace`, `Offer`, `SocialChannel`, `Delivery`, `ScrapingRun`, `Setting`, `InstagramPost` — todos herdam `TimestampedModel` |
| Scraping | :white_check_mark: Amazon + ML | `scrapers/amazon.py` (12 fontes, curl_cffi), `scrapers/mercado_livre.py` (BS4), runner unificado com normalizador |
| Curadoria | :white_check_mark: Selector funcional | `selector.py`: global_limit=20, por marketplace=10, desconto mín 20%, exclui já enviadas, exige slug para bridge_only |
| Orquestração | :white_check_mark: Loop principal | `run_bot`: scraping → publish_offers → selector → WhatsApp. `--dry-run`, `--once`, janela 00:00-06:00 BRT |
| Banco | :white_check_mark: SQLite WAL | `data/descontos_bot.db`, foreign_keys=ON, 986 ofertas ativas |
| Admin | :white_check_mark: Django Admin pt-BR | Todos os modelos registrados |
| Compliance Amazon | :white_check_mark: Script de validação | `scripts/amazon_compliance_check.py`, gate manual |

### 1.2 Distribuição

| Canal | Status | Detalhe |
|---|---|---|
| WhatsApp | :white_check_mark: Produção | `wa_service/` via Baileys, Delivery sent/failed/skipped, dry_run funcional |
| Telegram | :white_check_mark: Produção | `publish_telegram`, rate_limiter, gate `ALLOW_PRODUCTION_TELEGRAM_SEND` |
| Instagram | :warning: Engine pronto, publicação manual | `social_posts/`: 2.946 posts gerados (2.921 stories, 17 feed, 8 carrossel), 100% status=ready, **zero publicados** |
| Site público | :white_check_mark: Vercel | `site/`: index, oferta, r (redirect), links, sobre, disclosure. Consome `offers.json` |

### 1.3 Growth (estado atual)

| Componente | Status |
|---|---|
| Rastreamento de cliques | :x: Inexistente |
| UTMs padronizadas | :warning: Parcial — `links.json` tem UTMs manuais, `bridge_url` não propaga UTMs |
| Métricas por canal | :x: Inexistente |
| Dashboard de performance | :x: Inexistente |
| Score de qualidade | :x: Inexistente |
| Blacklist de ofertas | :x: Inexistente |
| Segmentação por categoria | :x: Inexistente |
| Funil público de aquisição | :warning: `links.html` existe mas é básico, sem CTAs persuasivos |

---

## 2. Mapa de Arquivos Principais

```
descontos.bot/
├── core/
│   ├── settings.py           # Config Django, apps, DB
│   ├── urls.py               # Rotas Django (admin apenas)
│   └── wsgi.py
├── apps/
│   ├── _base/models.py       # TimestampedModel (abstrato)
│   ├── offers/
│   │   ├── models.py         # Offer (FK→Marketplace, slug, preços, affiliate)
│   │   └── services/
│   │       ├── normalizer.py # Normalização de payload bruto
│   │       ├── repository.py # Upsert por offer_hash
│   │       ├── selector.py   # Seleção de ofertas por canal
│   │       └── site_publisher.py  # Geração de offers.json
│   ├── marketplaces/models.py # Marketplace (code, affiliate_tag)
│   ├── distribution/
│   │   ├── models.py         # SocialChannel, Delivery (UNIQUE offer+channel)
│   │   └── management/commands/
│   │       ├── publish_telegram.py
│   │       ├── seed_channels.py
│   │       └── seed_telegram_channel.py
│   ├── scraping/
│   │   ├── models.py         # ScrapingRun
│   │   ├── services/
│   │   │   ├── adapters.py   # build_adapter(code)
│   │   │   └── runner.py     # run_marketplace_scraping()
│   │   └── management/commands/
│   │       └── scrape_marketplace.py
│   ├── orchestration/management/commands/
│   │   ├── run_bot.py        # Loop principal
│   │   └── publish_offers.py # Gera e publica offers.json
│   ├── social_posts/
│   │   ├── models.py         # InstagramPost (Format, Status, posted_at)
│   │   └── management/commands/
│   │       ├── generate_instagram_post.py
│   │       ├── generate_instagram_story.py
│   │       └── generate_instagram_carousel.py
│   └── panel/models.py       # Setting (chave-valor dinâmico)
├── scrapers/
│   ├── base.py               # BaseScraper (ABC)
│   ├── amazon.py             # AmazonScraper (12 fontes, curl_cffi)
│   └── mercado_livre.py      # MercadoLivreScraper (BS4)
├── site/
│   ├── index.html            # Home com grid de cards + filtro marketplace
│   ├── r.html                # Bridge redirect (/r?slug=)
│   ├── oferta.html           # Página de detalhe
│   ├── links.html            # Página de links para bio
│   ├── offers.json           # Catálogo público (986 ofertas, 786 KB)
│   ├── links.json            # Links rastreados para bio Instagram
│   ├── assets/
│   │   ├── site.css           # Design system dark theme
│   │   └── site.js            # Lógica de renderização
│   └── vercel.json           # Rewrites clean URL
├── wa_service/               # Serviço WhatsApp (Node.js/Baileys)
├── data/                     # SQLite DB + exports
├── design_system/refs/       # Referência visual do design system
├── docs/
│   ├── PRD_DESCONTOS_BOT.md
│   ├── PLANO_EXECUCAO_SPRINTS.md
│   ├── SITE_ARCHITECTURE.md
│   ├── AMAZON_COMPLIANCE_EXECUTION_PLAN.md
│   └── GROWTH_PLAN_DESCONTOS_BOT.md (este documento)
├── scripts/
│   └── amazon_compliance_check.py
└── AGENTS.md                 # Regras para agentes no repositório
```

---

## 3. Plano de Execução — Sprints 2 a 7

### Ordem obrigatória

1. Sprint 2 — antes de aumentar volume de publicação
2. Sprint 3 — antes de usar Instagram como canal principal de aquisição
3. Sprint 4 — para transformar assets prontos em processo editorial real
4. Sprint 5 — para melhorar qualidade antes de escalar volume
5. Sprint 6 — para criar rotina de análise semanal
6. Sprint 7 — somente após estabilizar métricas e funil

---

### Sprint 2 — Métricas, UTMs e Rastreamento de Cliques

**Objetivo:** Implementar a base de analytics para medir cliques, canais e performance.

**Tarefas:**
- Criar model `ClickEvent` (FK→Offer, channel, source, medium, campaign, clicked_at, user_agent, ip_hash, redirect_url)
- Adaptar `r.html` para capturar parâmetros UTM e registrar clique
- Padronizar UTMs: `utm_source` (whatsapp/telegram/instagram/site), `utm_medium` (social/bio/direct), `utm_campaign` (offer_<id>)
- Garantir redirect funcional sem UTMs (fallback)
- Registrar ClickEvent via endpoint ou script serverless na Vercel
- Admin: visualização + filtros por canal, campanha, marketplace, data

**Entregáveis:**
- Model `ClickEvent` com migration
- Rota `/r` adaptada com rastreamento
- Padrão UTM documentado
- Admin funcional para ClickEvent

**Owner:** Didi (backend) + Dedé (site/r.html)
**Risco:** :warning: Médio — site é estático na Vercel; rastreamento exige endpoint. Avaliar Vercel Functions ou endpoint Django público.

---

### Sprint 3 — Página Pública de Entrada e Funil de Aquisição

**Objetivo:** Criar página para converter visitantes em membros dos canais.

**Tarefas:**
- Criar ou evoluir `links.html` com CTAs claros para WhatsApp, Telegram, Instagram e site
- Adicionar proposta de valor: headline + subtítulo persuasivo
- Adicionar disclosure de afiliado visível
- Todos os links com UTMs padronizadas (Sprint 2)
- Template responsivo mobile-first
- Meta tags OG/Twitter Card para previews sociais

**Copy sugerida:**
- Título: "Ofertas monitoradas por bot, selecionadas para você economizar melhor."
- Subtítulo: "Entre nos canais gratuitos e acompanhe achados da Amazon, Mercado Livre e outros marketplaces."
- CTAs: WhatsApp, Telegram, Instagram, Ver ofertas no site

**Entregáveis:**
- Página `/links` funcional com CTAs rastreáveis
- Responsivo mobile
- Meta tags sociais

**Owner:** Dedé (frontend) + Tião Macalé (copy)
**Risco:** :white_check_mark: Baixo — página estática, sem dependências de backend.

---

### Sprint 4 — Instagram Operacional e Status Editorial

**Objetivo:** Transformar Instagram de fábrica de assets em canal operacional de aquisição.

**Tarefas:**
- Revisar `InstagramPost.Status` (já existe: draft/ready/posted/rejected) — OK
- Garantir `posted_at` populado ao marcar como posted — campo já existe
- Criar ações no Admin: "Marcar como postado", "Marcar como rejeitado"
- Criar filtros no Admin por status e formato
- Criar comando `publish_bio_link` funcional (já existe esboço)
- Documentar rotina editorial mínima: 3 stories/dia, 1 feed/dia, 1 reel/semana
- Corrigir discrepância: 2.921 stories no banco vs ~15 assets em disco — revisar pipeline de renderização

**Rotina editorial mínima:**
1. Publicar 3 stories por dia
2. Publicar 1 post feed ou carrossel por dia
3. Publicar 1 reel por semana (formato já modelado, sem comando)
4. Priorizar ofertas com maior qualidade e apelo visual
5. Marcar todo conteúdo publicado como `posted`

**Entregáveis:**
- Admin actions para transição de status
- Filtros por status no Admin
- Documentação de rotina de publicação
- Pipeline de assets corrigido

**Owner:** Didi (backend/Admin) + Tião Macalé (rotina editorial)
**Risco:** :warning: Médio — publicação ainda manual (Meta Graph API não integrada). Automação de postagem direta bloqueada por restrição do plano.

---

### Sprint 5 — Qualidade da Curadoria, Blacklist e Score de Oferta

**Objetivo:** Reduzir ruído e aumentar percepção de valor.

**Tarefas:**
- Criar blacklist de termos: "usado", "reembalado", "avariado", "seminovo", "sem garantia", "produto indisponível"
- Implementar score de qualidade composto:
  - Peso alto: desconto percentual realista, economia absoluta
  - Peso médio: presença de imagem válida, título confiável, oferta recente
  - Peso baixo: marketplace de maior confiança
- Penalizar ofertas: sem imagem, preço original suspeito, desconto >99%
- Expor score no Admin (campo calculado ou método)
- Integrar score no `selector.py` para priorização

**Entregáveis:**
- Model/método de score no Offer
- Blacklist configurável (via Setting ou JSON)
- Admin: score visível e auditável
- Selector adaptado com score

**Owner:** Didi (backend) + Mussum (critérios de qualidade)
**Risco:** :warning: Médio — alterações no selector afetam pipeline de publicação. Validar com dry_run.

---

### Sprint 6 — Relatórios Semanais e Dashboard Operacional

**Objetivo:** Criar visão mínima de acompanhamento de crescimento.

**Tarefas:**
- Criar comando `weekly_report` com métricas:
  - Cliques por canal (depende Sprint 2)
  - Cliques por marketplace
  - Top 10 ofertas por clique
  - Posts Instagram publicados/semana
  - Posts Instagram pendentes
  - CTR estimado (cliques / envios)
- Exibir no Admin ou como página interna simples
- Export CSV para análise externa

**Entregáveis:**
- Comando `weekly_report`
- Visualização no Admin ou página interna
- Sem dependências externas (sem Grafana, Metabase)

**Owner:** Didi (backend) + Dedé (visualização)
**Risco:** :white_check_mark: Baixo — comando management, sem novas dependências.
**Dependência:** Sprint 2 (ClickEvent) concluída.

---

### Sprint 7 — Preparação para Expansão de Marketplaces

**Objetivo:** Preparar arquitetura para Shopee, Netshoes, Centauro.

**Tarefas:**
- Revisar abstração atual de marketplaces (já genérica via `Marketplace.code`)
- Identificar dependências específicas de Amazon e Mercado Livre
- Propor interface padrão para novos scrapers (`BaseScraper` já existe)
- Documentar requisitos mínimos: headers realistas, delays, detecção de CAPTCHA, normalizador
- Definir checklist de compliance por marketplace
- Estratégia de priorização: Shopee → Netshoes → Centauro

**Entregáveis:**
- Documento `docs/NEW_MARKETPLACE_GUIDE.md`
- Checklist de compliance por marketplace
- Nenhuma implementação de scraper novo nesta sprint (apenas preparação)

**Owner:** Didi (arquitetura) + Mussum (requisitos de produto)
**Risco:** :white_check_mark: Baixo — apenas documentação e planejamento.

---

## 4. Arquitetura — Produto, Distribuição e Growth

### 4.1 Produto (core)
```
scrapers/  →  apps/scraping/runner  →  apps/offers/normalizer  →  Offer (SQLite)
                                                       ↓
                                              selector.py (curadoria)
```

### 4.2 Distribuição (canais)
```
selector.py  →  message_builder  →  Delivery (WhatsApp/Telegram)
                                  →  InstagramPost.generate() (assets)
                                  →  site_publisher (offers.json → Vercel)
```

### 4.3 Growth (nova camada — Sprints 2-7)
```
ClickEvent  ←  /r?slug=&utm_*  (rastreamento)
     ↓
weekly_report  (métricas)
     ↓
score + blacklist  →  selector (qualidade)
     ↓
links.html  →  funil de aquisição
     ↓
InstagramPost.status  →  rotina editorial
```

---

## 5. Decisões Técnicas Recomendadas

| Decisão | Justificativa |
|---|---|
| **Vercel Functions para ClickEvent** | Site é estático na Vercel. Serverless function recebe POST do `/r` e escreve no SQLite ou envia para endpoint Django. Alternativa: endpoint Django com tunneling (ngrok) — mais frágil. |
| **UTM source/medium/campaign** | Padrão Google Analytics. `utm_source=whatsapp`, `utm_medium=social`, `utm_campaign=offer_<id>`. Suficiente para análise atual. |
| **Score como método Python, não campo** | Calculado sob demanda. Evita migração e recalculo em lote. Pode ser cacheado no `raw_payload` se necessário. |
| **Blacklist via Setting** | Configurável sem deploy. `Setting.objects.get(code='blacklist_terms')` retorna JSON. |
| **Instagram: sem automação de postagem** | Restrição explícita do plano. Meta Graph API só será integrada quando houver app aprovado. Por enquanto: assets automáticos + publicação manual. |
| **links.html (não /entrar)** | `/links` já existe. Evoluir o existente em vez de criar nova rota. |
| **Nada de Docker, FastAPI, SQLAlchemy** | Proibido por AGENTS.md. Stack: Django + SQLite + Node.js (wa_service). |

---

## 6. Dependências e Riscos

| Dependência | Impacto | Mitigação |
|---|---|---|
| Sprint 2 → Sprints 3, 6 | UTMs e ClickEvent são base para funil e relatórios | Executar Sprint 2 com prioridade máxima |
| Vercel Functions (Sprint 2) | Rastreamento depende de endpoint serverless | Validar viabilidade antes de implementar; fallback: pixel de tracking |
| Instagram manual (Sprint 4) | Sem automação, depende de operador humano publicar | Documentar rotina clara; reduzir atrito com Admin actions |
| Volume de dados (Sprint 6) | Métricas só terão significado com dados acumulados | Criar estrutura agora, significado virá com tempo |
| Compliance Amazon (todas as sprints) | Qualquer alteração em copy/links não pode violar ToS | Validar com `amazon_compliance_check.py` a cada sprint |
| Links afiliados (Sprint 5) | Tag Amazon já existe. Outros marketplaces precisam de aprovação | Não implementar links para marketplaces sem tag aprovada |

---

## 7. Validação da Sprint 1

- [x] Diagnóstico técnico do estado atual
- [x] Mapa dos arquivos principais
- [x] Documento `docs/GROWTH_PLAN_DESCONTOS_BOT.md`
- [x] Backlog técnico priorizado para as próximas sprints
- [x] Separação: Produto, Distribuição e Growth
- [x] Decisões técnicas recomendadas
- [x] Dependências e riscos

**Nenhuma alteração funcional foi feita nesta sprint.**

---

## 8. Próximo Passo

Aguardar ordem do PO para iniciar a **Sprint 2: Métricas, UTMs e Rastreamento de Cliques.**

---

## 9. Encerramento da Sprint 2 — 2026-05-29

**Status:** Parcialmente concluída. Tracking via beacon do navegador **abortado** por decisão de produto.

### O que ficou entregue e em produção

- App `apps/analytics/` completo: model `ClickEvent` + migration, Admin com filtros e busca, `link_builder.py` com `build_tracked_url`, `build_instagram_tracked_url`, `build_referral_hub_url`, `build_referral_suffix`, SubID nativo do Mercado Livre (`matt_word`).
- **UTMs padronizadas em todos os canais ativos** — WhatsApp/Telegram via `message_builder.py`; Instagram (story/feed/carousel/bio) via `post_generator.py`, `image_renderer.py`, `bio_link_publisher.py`.
- Bridge `/r?slug=…` mantido (compliance Amazon — diversidade de origem de cliques).
- `apps/analytics/management/commands/fetch_clicks.py` + `scripts/fetch-clicks.timer` (sincroniza KV→SQLite quando houver dados).
- Endpoints `site/api/click.js` e `site/api/clicks.js` deployados — em standby, **sem uso operacional**.

### O que foi abortado e por quê

A camada de tracking ponta-a-ponta (`/r` → `navigator.sendBeacon` → Vercel Function → Upstash → `fetch_clicks` → dashboard) apresentou múltiplos pontos de falha em série (adblockers, race condition de unload, detecção de framework da Vercel, mismatch de assinatura Node/Edge). Mais de uma semana investida sem evento real chegando no Upstash. Decisão do PO em 2026-05-29: **abortar** essa instrumentação e priorizar geração de tráfego.

### O que substitui o tracking customizado

Quando a operação retomar mensuração, a fonte de verdade passa a ser **relatórios oficiais dos marketplaces**:
- **Amazon Associates** — relatórios de cliques/pedidos exportáveis em CSV/XLSX.
- **Mercado Livre Afiliados** — relatórios por SubID (`matt_word`). O SubID já está propagado nos links (`dbot_<canal>_<offer_id>`) — basta consumir o export.

Esses relatórios entregam **conversões reais** (não só cliques), são imunes a adblocker, e dispensam infra própria. Não há perda de dado relevante.

### Próxima sprint a executar

Pular Sprint 3 (já entregue: `/links` redesenhado com CTAs + OG/Twitter + UTMs internas).
**Próxima ordem:** Sprint 4 — **Instagram Operacional e Status Editorial** (geração de tráfego — alinhado com a urgência de acessos e vendas).

### Backlog parado (a retomar quando voltar a mensuração)

- Ingestão de relatórios Amazon Associates (CSV/XLSX) em model próprio (provavelmente `AffiliateConversion`).
- Mesmo padrão para Mercado Livre Afiliados.
- Atualizar `/dashboard` pra consumir essa nova fonte (em vez do KV vazio).
- Avaliar se vale aposentar `site/api/click.js`, `site/api/clicks.js` e `fetch_clicks` ou manter como fallback.

---

## 10. Encerramento da Sprint 4 — 2026-05-30

**Status:** Concluída.

### O que ficou entregue

- **Admin actions para transição de status** — `mark_as_posted` e `mark_as_rejected` em `apps/social_posts/admin.py`. Popula `posted_at = now()` ao postar e zera ao rejeitar. Reporta quantidade alterada vs. já no estado de destino.
- **Filtros e busca no Admin Instagram** — `list_filter = ('format', 'status')`, `search_fields = ('primary_offer__title', 'caption')`, `autocomplete_fields` para ofertas. `list_display` com formato, status, oferta primária, `posted_at` e `created_at`.
- **Comando `publish_bio_link`** — saiu de esboço para serviço real (`apps/social_posts/services/bio_link_publisher.py`), integrado ao gerador de posts.
- **`fix_instagram_assets`** — comando que resolve a discrepância 2.921 stories no banco vs. ~15 assets em disco. Reconstrói/repara assets de posts em estado `ready`.
- **Rotina editorial documentada** — `docs/ROTINA_EDITORIAL_INSTAGRAM.md` (215 linhas): 3 stories/dia, 1 feed/dia, 1 reel/semana; janelas 10h/14h/19h BRT; critérios de priorização; respeito à janela de silêncio 00:00-06:00 BRT.
- **Freshness de 36h** — `apps/offers/services/freshness.py` define `SITE_OFFER_MAX_AGE_HOURS=36` (configurável). Aplicado no selector e no `site_publisher.py`. Evita publicar oferta velha em qualquer canal.
- **Frontend refinado** — `site/index.html`, `oferta.html`, `disclosure.html`, `sobre.html`, `links.html`, `r.html` ajustados; `site.css` evoluído (+94 linhas); minificados `site.min.css` e `site.min.js` gerados; favicons (`favicon.svg`, `favicon.ico`, `favicon-192.png`).
- **`short_description` com fallback** no `site_publisher.py` (evita card vazio no site).
- **`offer_title` propagado nos cliques** em `site/api/click.js` (rastreamento de qual produto foi clicado, não só o slug).
- **DevDeps de build** — `csso`, `sharp`, `terser` registrados em `site/package.json`.

### O que não foi feito (e por quê)

- **Automação de postagem direta no Instagram (Meta Graph API)** — bloqueada por restrição do plano da Meta, conforme já documentado na Sprint 4 do plano original. Continua manual; o operador usa as Admin actions para fechar o ciclo.

### Próxima sprint a executar

**Sprint 5 — Qualidade da Curadoria, Blacklist e Score de Oferta.**
Pré-requisitos satisfeitos: selector estável em `apps/curation/services/selector.py`, modelo `Setting` operacional para blacklist configurável, helpers `get_integer_setting`/`get_decimal_setting` prontos para receber `get_json_setting` análogo, e `Offer` com campos suficientes (`discount_pct`, `current_price`, `original_price`, `image_url`, `absolute_saving`, `raw_payload`) para calcular score sem migração.

