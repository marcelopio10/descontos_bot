# Arquitetura do Site Público — descontos-bot.vercel.app

> Documento produzido na Fase 0 do plano de Compliance Amazon Associates. Descreve o estado atual do repositório do site Vercel e fixa as decisões que orientam as Fases 3 e 4.

## 1. Estado atual

> **Atualização (2026-05-05):** por decisão operacional, o site estático foi integrado ao repo principal `descontos_bot.git` no diretório `site/`. As seções abaixo preservam o diagnóstico histórico do clone separado `descontos.bot-v0`, mas o fluxo vivo passa a usar `SITE_PUBLIC_DIR=site` e `SITE_REPO_LOCAL_PATH=.`. No Vercel, configurar Root Directory como `site/`; `site/vercel.json` mantém as rotas limpas `/oferta`, `/links`, `/sobre` e `/disclosure`.

### 1.1. Repositório local e remote

- Path local: `C:\Users\marce\Documents\Projetos\descontos.bot-v0` (acessado via WSL em `/mnt/c/Users/marce/Documents/Projetos/descontos.bot-v0`).
- Remote `origin` configurado: `https://github.com/marcelopio10/descontos.bot.git`.
- Branch ativa: `main`.
- Últimos commits: `1a93a67 Ajuste sessão ofertas com dados ML`, `1128496 Pacote monitoramento Vercel`, `5fcb811 Comentando a sesão Oferta de Hoje`.

> **Resolvido (2026-05-05):** PO confirmou que `descontos.bot.git` é o repo ativo do site Vercel (o que está aqui no clone local). `bot-monitor-ml` era o repo antigo, citado apenas para contexto histórico — não usar. Logo, a Fase 3 publica em `descontos.bot.git` na branch `main`.

### 1.2. Estrutura do site

```
descontos.bot-v0/
├── index.html                          # 28 KB — landing page única
├── plano_crescimento_grupo_whatsapp.html   # 11 KB — material interno
├── package.json                        # única dep: @vercel/analytics
├── package-lock.json
├── Identidade Visual/
│   └── identidade_descontos_bot.html
├── post/
│   ├── post_lancamento_1080px.png
│   ├── post_lancamento_feed.png
│   └── post_lancamento.svg
├── resoucrces/                         # (typo intencional do projeto)
│   ├── avatar_1080px.png
│   ├── avatar_110px.png
│   ├── avatar_320px.png
│   └── avatar_descontos_bot.svg
└── node_modules/                       # @vercel/analytics
```

Sem `vercel.json`. Sem `.github/workflows/`. Sem `offers.json` ou `ofertas.json`. Sem build step (deploy estático direto).

### 1.3. Fluxo de deploy

Não há GitHub Actions nem Vercel Deploy Hook. Inferido: Vercel está conectado ao repo via integração nativa GitHub e auto-deploya a cada push em `main`. Confirmar com o PO no acesso ao painel Vercel quando entrar a Fase 3.

### 1.4. Como o site renderiza ofertas hoje

`index.html:441` declara `let offers = []`. Existe um modal de admin com handler que faz `offers.unshift({name, store, price, oldPrice, tag, link})` quando o usuário do navegador insere uma oferta manualmente. Não há fetch para JSON externo, não há build estático, não há fonte de dados persistente — o array `offers` reseta a cada reload da página.

**Conclusão operacional:** o site não está sendo alimentado por dados reais. Funciona como landing page com signup, e a área de ofertas é vazia para visitantes. O plano de "rotina antiga de `offers.json`" mencionado pelo PO **não existe** neste repositório nem em formato vivo.

## 2. Conteúdo a remover na Fase 4

Mapeamento direto da tabela 4.4 do plano + regras 1, 4, 7 da seção 21.2 do PRD.

| Linha em `index.html` | Texto atual | Decisão Fase 4 |
|---|---|---|
| 7 (meta description) | "cupons exclusivos e as melhores ofertas do Brasil" | reescrever sem "cupons exclusivos" |
| 190, 195 | "💰 ECONOMIZE AGORA" (ticker) | remover |
| 191, 196 | "🔔 CADASTRE-SE GRÁTIS" (ticker) | remover |
| 325 | título de seção "Cupons exclusivos" | remover seção inteira |
| 354 | feature "Frete grátis" | remover ou condicionar a dado real |
| 417 | placeholder "Frete grátis, Relâmpago" | remover (modal admin some) |
| 455 | label "🚚 Frete grátis" no card | remover |
| (form de signup ao todo) | inputs `nameInput` + `emailInput` + `handleSignup` | remover — captura de e-mail não é função do site no novo desenho |
| ausente | disclosure "Como Associado da Amazon, ganho por compras qualificadas" | **adicionar** em home, página de oferta, rodapé global, `/disclosure.html` |

## 3. Decisões fixas para as Fases 3 e 4

### 3.1. Padrão de publicação — Padrão A (git push)

`apps/orchestration/management/commands/publish_offers.py --push` fará:

1. `cd $SITE_REPO_LOCAL_PATH` (default: repo principal `descontos_bot.git`).
2. `git pull --ff-only` para garantir base atualizada.
3. Copiar `offers.json` (e na Fase 6, `links.json`) para `SITE_PUBLIC_DIR` (default: `site/`).
4. `git add` + `git commit -m "data: refresh offers.json (<count> offers)"` apenas se houver diff.
5. `git push origin main`.
6. Vercel detecta o push e auto-deploya.

Variáveis de ambiente a adicionar em `.env`:

```
SITE_PUBLIC_DIR=site
SITE_REPO_LOCAL_PATH=.
SITE_REPO_BRANCH=main
```

Não usar `git config user.*` global; passar `-c user.email` e `-c user.name` no commit do push para isolar do git config do usuário.

### 3.2. Formato de `offers.json` v2.0 (Fase 3)

Não há legado a manter. Formato canônico:

```json
{
  "version": "2.0",
  "generated_at": "2026-05-05T14:30:00-03:00",
  "site_base_url": "https://descontos-bot.vercel.app",
  "disclosure": "Como Associado da Amazon, ganho por compras qualificadas.",
  "offers": [
    {
      "id": 123,
      "slug": "fone-bluetooth-jbl-tune-510bt-azul-123",
      "marketplace": "amazon",
      "title": "Fone JBL Tune 510BT Bluetooth Azul",
      "short_description": "Fone supra-auricular sem fio com até 40h de bateria. Conexão estável via Bluetooth 5.0.",
      "current_price": 199.90,
      "original_price": 349.00,
      "discount_pct": 43.0,
      "image_url": "https://m.media-amazon.com/images/I/71xxxxxxx.jpg",
      "affiliate_link": "https://www.amazon.com.br/dp/B08PZHYWJS?tag=desconto.bot-20",
      "detail_url": "/oferta?slug=fone-bluetooth-jbl-tune-510bt-azul-123",
      "price_collected_at": "2026-05-05T13:20:00-03:00"
    }
  ]
}
```

### 3.3. Estrutura de páginas a criar (Fase 4)

| Rota | Arquivo no repo | Implementação |
|---|---|---|
| `/` | `index.html` (reformado) | consome `offers.json`, renderiza cards, cada card linka para `/oferta?slug=…` |
| `/oferta?slug=<slug>` | `oferta.html` | lê `?slug=` da query, busca em `offers.json`, renderiza com 8 elementos obrigatórios (PRD 21.4) |
| `/links` | `links.html` | linktree próprio para bio Instagram, consome `links.json` |
| `/sobre` | `sobre.html` | descrição honesta do projeto |
| `/disclosure` | `disclosure.html` | texto completo do disclosure Amazon |

Para MVP **fica em Opção A** (query string em `oferta.html?slug=…`). SEO não é prioridade enquanto a Amazon não aprovar; o tempo economizado em `vercel.json` rewrites + pré-renderização compensa a feiura da URL.

### 3.4. Nada de signup, nada de captura de e-mail

O novo desenho do site é puramente informacional. Sem forms, sem newsletter, sem "cadastre-se grátis". Isso elimina automaticamente os textos da regra 7 da seção 21.2 que sugerem benefício pessoal para o usuário ao clicar no link.

### 3.5. Janela de validade e ordenação no `offers.json`

`apps/offers/services/site_publisher.py::_get_publishable_offers()` é o único ponto que monta a lista pública. Ele aplica:

1. **Filtro de recência** — `last_seen_at >= now() - SITE_OFFER_MAX_AGE_HOURS`. O default é 36 horas; `SITE_OFFER_MAX_AGE_HOURS` em `.env` permite ajustar sem deploy. Valores ausentes, vazios ou inválidos caem no default. `last_seen_at` é atualizado a cada confirmação do scraper (ver `apps/offers/services/repository.py`), portanto representa "última coleta" — se o scraper não reencontrou a oferta nas últimas 36 horas, ela sai do site.
2. **Ordenação determinística** — `-last_seen_at, -discount_pct, title, id`. A ordenação acontece no banco; duas execuções com os mesmos dados produzem o mesmo `offers.json` (e o `_has_real_payload_change` continua detectando diff sem ruído).
3. **Preservação no banco** — registros fora da janela continuam persistidos. A regra é exclusivamente de exibição; nada é deletado.
4. **Logs** — cada publicação loga `cutoff`, `total_antes`, `elegiveis` e `ignoradas_por_expiracao` em `apps.offers.services.site_publisher`.

## 4. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Push para `main` quebra deploy ativo | Antes do primeiro `--push`, rodar `--dry-run` (apenas grava o JSON local em `data/exports/offers.json`) e revisar diff. |
| Site recém-deployado quebrado, grupo já redirecionado para `bridge_url` | Sequência de execução: site reformado MVP (Fase 4 mínima) → push do primeiro `offers.json` → Fase Mitigação ativa o `bridge_only` no grupo. Nunca o inverso. |
| Vercel está conectado a outro repo | Ajustar o projeto Vercel para apontar para `descontos_bot.git` antes do próximo deploy. |
| Conflito de merge com mudanças manuais no site | `publish_offers --push` faz `git pull --ff-only` primeiro; se falhar, aborta sem commit e loga para revisão humana. |

## 5. Login do site privado (Sprint 7A)

As páginas analíticas/administrativas e seus dados deixam de ser públicas. Autenticação de **operador único** via Vercel Edge Middleware + Functions, sem banco e sem segredo no código.

### 5.1. Rotas

| Rota | Acesso |
|---|---|
| `/`, `/oferta`, `/links`, `/sobre`, `/disclosure`, `/r`, `/api/click`, `/api/clicks`, `/offers.json`, `/links.json`, `/assets/*`, `/og.png` | **Público** |
| `/dashboard`, `/inteligencia` (com/sem `.html`) | **Privado** |
| `/affiliate-summary.json`, `/market-intel.json` | **Privado** (JSON sensível) |
| prefixos `/admin`, `/analise`, `/analysis`, `/ops`, `/private` | **Privado** (reserva futura) |

A proteção é **fail-closed por allowlist de matcher**: `site/middleware.js` só executa nas rotas privadas declaradas em `config.matcher`. Qualquer rota fora do matcher nunca passa pelo middleware e permanece pública.

### 5.2. Componentes

- `site/_auth/token.js` — assina/verifica o cookie de sessão (HMAC-SHA256, Web Crypto) e gera o hash da senha.
- `site/_auth/cookie.js` — atributos do cookie (`HttpOnly`, `SameSite=Lax`, `Secure` em HTTPS, `Path=/`, `Max-Age`).
- `site/api/login.js` / `logout.js` / `session.js` — emite/limpa/inspeciona a sessão.
- `site/middleware.js` — redireciona páginas anônimas para `/login?next=<rota>` e responde `401` para JSON sensível.
- `site/login.html` + `site/assets/auth.js` — tela de login (pt-BR, anti-open-redirect).
- `site/assets/logout.js` — botão "Sair" das páginas privadas.

O cookie `descontos_bot_session` é enviado automaticamente no `fetch` same-origin do dashboard/inteligência, então os JSONs protegidos continuam carregando para o operador logado sem alterar o frontend.

### 5.3. Dependência

`@vercel/edge` (helper `next()` do middleware) entra em `site/package.json`. Rodar `npm install` em `site/` antes do `vercel dev`; no deploy a Vercel instala automaticamente.

### 5.4. Variáveis

Ver `docs/ENVIRONMENT.md` e `.env.example`. `SITE_AUTH_PASSWORD_HASH` é hash (não senha pura), gerado por `site/scripts/hash-password.mjs`.

## 6. Endpoints de tracking de clique — STANDBY

`site/api/click.js`, `site/api/clicks.js` e o comando `apps/analytics/management/commands/fetch_clicks.py` permanecem no repo como **fallback em standby**, sem uso operacional. A decisão de 2026-06-02 definiu os relatórios oficiais de afiliados (`AffiliateConversion` → `affiliate-summary.json`) como fonte de verdade de mensuração; o tracking próprio por clique foi abortado por fragilidade (adblock, race condition, infra). Estes endpoints continuam **públicos** (na allowlist do middleware) e dependem do Vercel KV; não removê-los sem antes confirmar que nenhum canal ainda gera links `/r` com beacon.
