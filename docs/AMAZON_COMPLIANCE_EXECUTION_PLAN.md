# Amazon Associates Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** destravar a aprovação no Amazon Associates sem interromper scraping, curadoria, distribuição WhatsApp, banco SQLite ou site público.

**Architecture:** o PRD continua sendo a fonte de verdade. Este documento é o roteiro operacional separado para executar as fases de compliance em ordem, com gates bloqueantes e mudanças aditivas. O site público `https://descontos-bot.vercel.app` funciona como funil rastreável; canais privados recebem somente `bridge_url`; links afiliados diretos ficam restritos a fontes aprovadas pela Amazon.

**Tech Stack:** Django 6.0.4, Python 3.11+, SQLite em `data/descontos_bot.db`, Node.js/Baileys preservado em `wa_service/`, site HTML/CSS/JS puro no Vercel.

---

## 1. Diretiva Principal

O projeto está em produção e não pode parar de funcionar.

Em qualquer conflito entre seguir este plano literalmente e preservar a operação atual, preservar a operação vence. Mudanças em banco devem ser aditivas. Alterações no fluxo de envio precisam manter rollback claro. O serviço `wa_service/` não deve ser alterado neste plano.

## 2. Regras Não Negociáveis

- PRD-first: antes de código novo em qualquer fase, atualizar `docs/PRD_DESCONTOS_BOT.md` e registrar entrada em `## 22. Changelog — Amazon Compliance`.
- Execução sequencial no caminho crítico: Fase 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 7. Fase 6 pode começar após Fase 1 verde, mas só é útil após a Fase 4.
- Gates bloqueantes: se o critério de aceite da fase falhar, parar, diagnosticar e pedir confirmação antes de prosseguir.
- Branch única: `feat/amazon-compliance`.
- Commits atômicos: um commit por sub-passo numerado.
- Código, identificadores, comentários e commits em inglês. Conteúdo visível ao operador e público em pt-BR.
- Tag oficial: `descontos.bot-20`, exposta via `settings.py` / `.env`, sem espalhar hardcode.
- Toda URL Amazon canônica deve passar por `Offer.affiliate_link`.
- WhatsApp grupo fechado nunca recebe afiliado direto; recebe somente `Offer.bridge_url`.
- Não criar Docker, FastAPI, Uvicorn, SQLAlchemy, Jinja2, outro banco, nem suíte automatizada como entregável do MVP.

## 3. Estado Já Validado na Fase 0

- PRD existente localizado em `docs/PRD_DESCONTOS_BOT.md`.
- Seções de Amazon Compliance já adicionadas ao PRD: `21` e `22`.
- Documento de arquitetura do site já criado em `docs/SITE_ARCHITECTURE.md`.
- Branch ativa esperada: `feat/amazon-compliance`.
- Site Vercel integrado por decisão posterior em `site/` no repo principal `https://github.com/marcelopio10/descontos_bot.git`.
- Repo antigo `bot-monitor-ml` não deve ser usado.
- A rotina antiga de `offers.json` não foi encontrada neste repositório nem no site atual; o site atual não consome JSON dinâmico.
- Formato canônico novo: `offers.json` versão `2.0`.

## 4. Política Amazon — Invariantes do Sistema

Cada regra abaixo deve ter código, conteúdo, script de compliance, verificação manual ou combinação deles.

1. Disclosure obrigatório: toda página com link afiliado exibe "Como Associado da Amazon, ganho por compras qualificadas." próximo ao primeiro link e no rodapé.
2. URL canônica: `https://www.amazon.com.br/dp/<ASIN>?tag=descontos.bot-20`. Nunca URL de busca, nunca sem tag, nunca tag de outra conta.
3. Preço com timestamp: todo preço exibido tem "Preço coletado em DD/MM/AAAA HH:mm. O valor pode variar."
4. Sem mimetismo: site não usa cor laranja Amazon, logo Amazon decorativo ou layout que imite Amazon.
5. Conteúdo original: cada página de oferta tem descrição própria em pt-BR; nunca copiar texto literal da Amazon.
6. Grupo fechado nunca recebe afiliado direto: somente `bridge_url`.
7. Linguagem proibida em qualquer canal: "compre aqui e ganhe desconto exclusivo", "cashback", "doação por compra", "favorite este link", "cupom exclusivo Amazon", "imitação", "réplica".
8. O site não pode parecer apenas um site de cupons; páginas de oferta precisam de conteúdo real, não só card e botão.

## 5. Fase 0 — Reconhecimento do Código Existente

**Status:** concluída e documentada.

**Objetivo:** entender PRD, código, site Vercel e rotina antiga de publicação antes de implementar.

**Arquivos:**
- Criado: `docs/SITE_ARCHITECTURE.md`
- Modificado: `docs/PRD_DESCONTOS_BOT.md`

**Critério de aceite:**
- [x] PRD localizado.
- [x] Branch `feat/amazon-compliance` criada.
- [x] Site Vercel inspecionado e documentado.
- [x] Rotina antiga de `offers.json` buscada; não encontrada.
- [x] Repo correto do Vercel resolvido: integrado em `descontos_bot.git` no diretório `site/`.

**Comandos de verificação:**

```bash
test -f docs/SITE_ARCHITECTURE.md
git branch --show-current
git log --oneline -6
```

## 6. Fase 1 — Modelagem de Dados para Compliance

**Status:** concluída e documentada no PRD.

**Objetivo:** schema suporta slug público, ASIN, override manual, conteúdo original, timestamp de preço e estratégia de canal.

**Impacto em produção:** migrações Django aditivas. Rollback operacional: não ativar uso dos novos campos no envio até Fases 3, 4 e 5 estarem verdes.

### 1.1. Offer

**Arquivos:**
- Modificar: `apps/offers/models.py`
- Criar: migração em `apps/offers/migrations/`

**Adicionar campos:**
- `slug = SlugField(max_length=220, unique=True, db_index=True)`
- `asin = CharField(max_length=20, blank=True, db_index=True)`
- `affiliate_url_override = URLField(blank=True)`
- `short_description = TextField(blank=True)`
- `price_collected_at = DateTimeField(null=True, blank=True)`

**Adicionar properties:**
- `affiliate_link`: override manual > URL canônica Amazon por ASIN > `product_url`.
- `bridge_url`: `settings.PUBLIC_SITE_BASE_URL.rstrip('/') + '/oferta?slug=' + slug`.
- `absolute_saving`: diferença entre preço original e atual.

**Observação:** o PRD e `docs/SITE_ARCHITECTURE.md` definem MVP com query string (`/oferta?slug=...`). Portanto `bridge_url` deve usar query string até decisão explícita por rewrite.

### 1.2. SocialChannel

**Arquivos:**
- Modificar: `apps/distribution/models.py`
- Criar: migração em `apps/distribution/migrations/`

**Adicionar campo:**
- `link_strategy` com choices `affiliate_direct` e `bridge_only`, default `bridge_only`.

**Regra:** `whatsapp_group` e o valor legado `whatsapp`, quando representar grupo, devem permanecer `bridge_only`.

### 1.3. Marketplace

**Arquivos:**
- Modificar: `apps/marketplaces/models.py`
- Criar: migração em `apps/marketplaces/migrations/`

**Adicionar campo:**
- `affiliate_tag = CharField(max_length=50, blank=True)`

**Data migration:**
- `Marketplace(code='amazon').affiliate_tag = settings.AMAZON_AFFILIATE_TAG`

### 1.4. Settings e ambiente

**Arquivos:**
- Modificar: `core/settings.py`
- Modificar: `.env.example`

**Adicionar:**

```python
PUBLIC_SITE_BASE_URL = os.environ.get('PUBLIC_SITE_BASE_URL', 'https://descontos-bot.vercel.app')
AMAZON_AFFILIATE_TAG = os.environ.get('AMAZON_AFFILIATE_TAG', 'descontos.bot-20')
```

**Compatibilidade:** preservar `AMAZON_ASSOCIATE_TAG` se já for usado por scraper, aceitando fallback para não quebrar o fluxo atual.

### 1.5. Backfill

**Arquivos:**
- Criar: migração de dados em `apps/offers/migrations/`

**Backfill obrigatório:**
- Gerar `slug` com `slugify(normalized_title or title or 'oferta')[:200] + '-' + id`.
- Extrair `asin` de `product_url` Amazon via regex `/dp/([A-Z0-9]{10})`.
- Preencher `price_collected_at` com `last_seen_at`.

**Antes de migrar em produção:**

```bash
python3 manage.py makemigrations --dry-run
python3 manage.py migrate --plan
```

Executar `migrate` somente com autorização do PO.

### Critério de aceite Fase 1

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py shell -c "
from apps.offers.models import Offer
o = Offer.objects.filter(marketplace__code='amazon', asin__gt='').first()
assert o, 'no amazon offer with ASIN found'
assert o.slug, f'slug empty for {o.id}'
assert o.affiliate_link.startswith('https://www.amazon.com.br/dp/'), o.affiliate_link
assert 'tag=descontos.bot-20' in o.affiliate_link, o.affiliate_link
assert '/oferta' in o.bridge_url and 'slug=' in o.bridge_url, o.bridge_url
print('PASS', o.affiliate_link, '|', o.bridge_url)
"
```

## 7. Fase 2 — Scraper Amazon e Normalização com ASIN

**Status:** concluída e documentada no PRD.

**Objetivo:** ofertas Amazon novas entram com ASIN preenchido e ofertas sem ASIN são rejeitadas no pipeline.

**Impacto em produção:** risco de reduzir volume de ofertas Amazon se parser falhar. Rollback: manter backfill e logar rejeições sem derrubar ciclo; Mercado Livre não pode ser afetado.

**Arquivos:**
- Modificar: `scrapers/amazon.py`
- Modificar: `apps/offers/services/normalizer.py`
- Possivelmente modificar: `apps/scraping/services/runner.py`

**Regras:**
- `external_id` canônico da Amazon é ASIN.
- Normalizer extrai ASIN de `product_url` ou payload equivalente.
- Amazon sem ASIN não é salva como oferta compliance.
- Log em pt-BR operacional: "Oferta Amazon rejeitada: ASIN não encontrado."

**Critério de aceite Fase 2:**

```bash
python3 manage.py check
python3 manage.py scrape_marketplace amazon --max-pages 1
python3 manage.py shell -c "
from apps.offers.models import Offer
qs = Offer.objects.filter(marketplace__code='amazon', asin='')
print(f'Amazon offers without ASIN: {qs.count()} (expected: 0 after fix)')
assert qs.count() == 0
"
```

## 8. Fase 3 — Geração de `offers.json` para o Site

**Status:** concluída e documentada no PRD.

**Objetivo:** Django gera `offers.json` versão `2.0` para o site estático.

**Impacto em produção:** sem `--push`, impacto zero. Com `--push`, pode alterar deploy Vercel conectado ao repo principal; usar `--dry-run`/`--output` antes.

**Arquivos:**
- Criar: `apps/offers/services/site_publisher.py`
- Criar: `apps/orchestration/management/commands/publish_offers.py`
- Modificar: `core/settings.py`
- Modificar: `.env.example`
- Modificar: `docs/PRD_DESCONTOS_BOT.md`

**Payload canônico:**
- `version: '2.0'`
- `generated_at`
- `site_base_url`
- `disclosure`
- `offers[]` com `id`, `slug`, `marketplace`, `title`, `short_description`, `current_price`, `original_price`, `discount_pct`, `image_url`, `affiliate_link`, `detail_url`, `price_collected_at`.

**Publicação:**
- Default seguro: escrever em `data/exports/offers.json`.
- `--push`: copiar para `SITE_PUBLIC_DIR/offers.json`, fazer `git pull --ff-only` em `SITE_REPO_LOCAL_PATH`, commit apenas se houver diff, push para `SITE_REPO_BRANCH`.
- Não usar `git config user.*` global; usar `git -c user.name=... -c user.email=... commit`.

**Integração com scheduler:** somente após Fase 4 verde. Até lá, não chamar `publish_offers --push` automaticamente.

**Critério de aceite Fase 3:**

```bash
python3 manage.py publish_offers --output=/tmp/offers.json
python3 -c "
import json
data = json.load(open('/tmp/offers.json'))
assert data['version'] == '2.0'
assert data['disclosure'].startswith('Como Associado')
assert len(data['offers']) > 0
o = data['offers'][0]
assert 'tag=descontos.bot-20' in o['affiliate_link'] or 'amzlink.to' in o['affiliate_link'] or 'amzn.to' in o['affiliate_link']
assert o['detail_url'].startswith('/oferta?slug=')
print('PASS')
"
```

## 9. Fase 4 — Site Vercel HTML/CSS/JS

**Status:** concluída e documentada no PRD.

**Objetivo:** site consome `offers.json`, mostra home, página de oferta, `/links`, `/sobre` e `/disclosure` com regras Amazon.

**Impacto em produção:** alto, porque altera o site Vercel dentro do repo principal. Rollback: reverter commit do site ou não fazer push até validação local.

**Repositório:** `https://github.com/marcelopio10/descontos_bot.git`, diretório `site/`.

**Arquivos esperados no site:**
- Modificar: `index.html`
- Criar: `oferta.html`
- Criar: `links.html`
- Criar: `sobre.html`
- Criar: `disclosure.html`
- Opcional: arquivos CSS/JS separados se o repo já suportar.

**Decisão MVP:** Opção A, página única `oferta.html?slug=...`, sem `vercel.json`.

**Home:**
- Consome `offers.json`.
- Cards linkam para `/oferta.html?slug=<slug>`, não diretamente para Amazon.
- Disclosure visível.
- Remover linguagem proibida documentada em `docs/SITE_ARCHITECTURE.md`.

**Página de oferta:**
- H1 com título.
- Imagem do produto.
- Disclosure próximo ao CTA.
- Preço atual, preço original e desconto.
- Timestamp: "Preço coletado em DD/MM/AAAA HH:mm. O valor pode variar."
- `short_description`; fallback neutro se vazio.
- CTA "Ver na Amazon" com `rel="sponsored nofollow noopener"`.
- Disclosure no rodapé.

**Critério de aceite Fase 4:**

- [ ] Home consome `offers.json` e renderiza cards.
- [ ] Página de oferta tem os 8 elementos obrigatórios.
- [ ] Disclosure aparece em home, página de oferta, rodapé global e `/disclosure.html`.
- [ ] Link Amazon contém `tag=descontos.bot-20` ou usa `amzlink.to`/`amzn.to`.
- [ ] Textos proibidos foram removidos.
- [ ] Validação manual no navegador local antes do push.

## 10. Fase 5 — Roteamento por Canal

**Status:** concluída e documentada no PRD.

**Objetivo:** `message_builder` escolhe `affiliate_link` para canais aprovados e `bridge_url` para canais privados.

**Impacto em produção:** altera mensagem enviada. Rollback: voltar canais para configuração anterior, mas nunca reenviar afiliado direto a grupo fechado depois de ativar compliance.

**Arquivos:**
- Modificar: `apps/curation/services/message_builder.py`
- Modificar ou criar migration/data command para canais em `apps/distribution/`
- Modificar: `docs/PRD_DESCONTOS_BOT.md`

**Template oficial de referência:**

O template abaixo, derivado de `post_generator.py`, é o formato operacional para canais privados. A Fase 5 altera o link final conforme `link_strategy` e mantém a redação dentro das frases permitidas pela regra 7 da seção 21.2 do PRD.

```text
📦 *{title}*

{badge}
━━━━━━━━━━━━━━━━━━━━━

💰 ~De {original_price}~
✅ *Por apenas {current_price}*
🏷️ *{discount_pct}% OFF*

🛒 Compre aqui 👇
{link}

⏰ Oferta por tempo limitado!
━━━━━━━━━━━━━━━━━━━━━
🤖 @descontos.bot
```

`badge` é escolhido por intensidade do desconto: `🚨 *OFERTA IMPERDÍVEL* 🚨` em `>= 50%`, `🔥 *ALERTA DO BOT* 🔥` em `>= 30%`, `⚡ *BOT ACHOU DESCONTO* ⚡` no demais.

**Regra:**
- `channel.link_strategy == 'affiliate_direct'`: usar `offer.affiliate_link`.
- Caso contrário: usar `offer.bridge_url`.

**Critério de aceite Fase 5:**

```bash
python3 manage.py check
python3 manage.py shell -c "
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer
from apps.curation.services.message_builder import build_message
ch_group = SocialChannel.objects.filter(channel_type__in=['whatsapp_group', 'whatsapp']).first()
o = Offer.objects.filter(marketplace__code='amazon', asin__gt='').first()
assert ch_group, 'no WhatsApp group/legacy channel found'
assert o, 'no Amazon offer found'
msg_group = build_message(o, ch_group)
assert '/oferta' in msg_group, 'group must use bridge_url'
assert 'tag=descontos.bot' not in msg_group, 'group must NEVER carry affiliate tag'
print('group OK')
"
```

## 11. Fase 6 — Engine de Posts Instagram

**Objetivo:** gerar tráfego rastreável Instagram -> Amazon, com link afiliado direto e postagem manual.

**Sequência:** pode iniciar depois da Fase 1 verde, mas só publicar de verdade após Fase 4 verde.

**Impacto em produção:** baixo se apenas gerar assets PNG. Não automatizar postagem no Instagram.

**Identidade visual:** assets gerados devem respeitar `design_system/refs/design_system.html` como padrão visual oficial, incluindo paleta, tipografia declarada e linguagem de post/story.

**Arquivos:**
- Criar app: `apps/social_posts/`
- Criar: `apps/social_posts/models.py`
- Criar: `apps/social_posts/admin.py`
- Criar serviços: `image_renderer.py`, `caption_builder.py`, `link_builder.py`, `bio_link_publisher.py`
- Criar commands: `generate_instagram_post.py`, `generate_instagram_carousel.py`, `generate_instagram_story.py`, `publish_bio_link.py`
- Criar assets PNG estáticos e diretório de saída em `media/instagram_posts/`

**Modelo:** `InstagramPost` herda `TimestampedModel`, com formato (`feed`, `carousel`, `story`, `reel`), status (`draft`, `ready`, `posted`, `rejected`), `primary_offer`, `related_offers`, `asset_paths`, `caption`, `sticker_target_url`, `posted_at`.

**UTM padrão:**
- `utm_source=instagram`
- `utm_medium=bio|story|reel|carousel_link`
- `utm_campaign=offer_<id>`
- `utm_content` opcional.

**Link padrão:** Instagram é fonte aprovada e usa `Offer.affiliate_link` direto com UTMs. `Offer.bridge_url` fica restrito a canais privados como grupos de WhatsApp.

**Critério de aceite Fase 6:**

```bash
python3 manage.py generate_instagram_post --top=1
python3 manage.py generate_instagram_carousel --count=5
python3 manage.py generate_instagram_story --top=1
python3 manage.py publish_bio_link --output=/tmp/links.json
python3 -c "
import json
d = json.load(open('/tmp/links.json'))
assert len(d['items']) >= 5
for item in d['items']:
    assert 'utm_source=instagram' in item['tracked_url']
    assert 'utm_medium=bio' in item['tracked_url']
print('links OK')
"
```

**Checklist humano:**
- [ ] Bio do Instagram aponta para `https://descontos-bot.vercel.app/links`.
- [ ] Bio contém disclosure Amazon.
- [ ] Conta é profissional.
- [ ] Primeiros posts manuais respeitam intervalo de 4-6 horas.

## 12. Fase 7 — Compliance Final

**Status:** concluída e documentada no PRD.

**Objetivo:** validar tudo antes de solicitar nova revisão Amazon.

**Arquivos:**
- Criar: `scripts/amazon_compliance_check.py`
- Modificar: `docs/CHECKLIST_PRE_MERGE.md`
- Modificar: `docs/PRD_DESCONTOS_BOT.md`

**Checks automatizados:**
- Home HTTP 200, disclosure e sem texto proibido.
- `offers.json` com disclosure e links Amazon com tag correta.
- `oferta.html?slug=<slug>` com disclosure e timestamp.
- `links.json` com disclosure, mínimo 5 itens e UTM de bio.
- `/links` ou `/links.html` existe e mostra disclosure.

**Execução local:** o script sobe um servidor HTTP temporário apontando para `site/` para validar status 200 e conteúdo sem depender de deploy externo.

**Critério de aceite Fase 7:**

```bash
python3 scripts/amazon_compliance_check.py
```

Saída esperada:

```text
ALL COMPLIANCE CHECKS PASSED
```

**Checklist humano antes da revisão:**
- [ ] Cadastrar `https://descontos-bot.vercel.app` como fonte primária no portal Amazon Associates.
- [ ] Cadastrar Instagram oficial com URL completa.
- [ ] Criar canal público de WhatsApp e cadastrar URL pública no portal.
- [ ] Remover grupo fechado de WhatsApp das fontes do portal.
- [ ] Publicar 5+ ofertas no Instagram manualmente.
- [ ] Confirmar `publish_offers` em ciclos regulares.
- [ ] Aguardar mínimo 14 dias de tráfego real.
- [ ] Conferir cliques no painel Amazon com origem do domínio cadastrado.
- [ ] Obter pelo menos 3 vendas qualificadas quando aplicável.
- [ ] Só então solicitar revisão ou aguardar revisão automática.

## 13. Fase 8 — Contingência para Rejeição Futura

**Objetivo:** resposta operacional se a Amazon questionar origem de tráfego ou grupo fechado.

**Ações imediatas:**
- Setar todos os canais não cadastrados para `bridge_only`.
- Auditar entregas dos últimos 30 dias procurando `tag=descontos.bot` em mensagens para grupo.
- Se houver histórico ruim, documentar como bug corrigido pela Fase 5.
- Reforçar tráfego via site, Instagram e canal público.

**Comando de auditoria:**

```bash
python3 manage.py shell -c "
from apps.distribution.models import Delivery
from datetime import timedelta
from django.utils import timezone
bad = Delivery.objects.filter(
    sent_at__gte=timezone.now() - timedelta(days=30),
    social_channel__channel_type='whatsapp_group',
    message__icontains='tag=descontos.bot'
)
print(f'Suspect deliveries: {bad.count()} (must be 0)')
"
```

## 14. Loop Obrigatório por Fase

Antes de executar qualquer fase:

1. Read: reler a fase, listar arquivos tocados e comandos de aceite.
2. Diff plan: declarar mudanças, risco de produção e rollback.
3. PRD update: atualizar PRD e commitar antes do código.
4. Implement: editar por sub-passo, com commits atômicos.
5. Validate: executar literalmente o gate da fase.
6. Report: resumir mudanças, riscos residuais e pedir autorização para próxima fase.

## 15. Ordem Resumida

| # | Fase | Bloqueia próxima? | Status |
|---|---|---|---|
| 0 | Reconhecimento + site architecture | Sim | Concluída |
| 1 | Modelagem de dados | Sim | Concluída |
| 2 | ASIN no scraper/normalizer | Sim | Concluída |
| 3 | `offers.json` v2 + publisher | Sim | Concluída |
| 4 | Site Vercel compliance | Sim | Concluída |
| 5 | Roteamento por canal | Sim | Concluída |
| 6 | Instagram posts + `/links` | Não no caminho crítico | Concluída |
| 7 | Compliance final | Sim | Concluída |
| 8 | Contingência | Sob demanda | Pós-MVP (backlog) |

**Caminho crítico:** Fase 0 -> Fase 1 -> Fase 2 -> Fase 3 -> Fase 4 -> Fase 5 -> Fase 7.

## 16. Fora do Escopo

- Score de qualidade com IA.
- Histórico avançado de preço.
- Painel customizado.
- Novos marketplaces.
- Automação de postagem no Instagram.
- Alterações em `wa_service/`.
- Suíte automatizada como entregável do MVP.
