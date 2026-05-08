# PRD — descontos.bot

## 1. Visão Geral do Produto

O `descontos.bot` é uma plataforma local para coletar, normalizar, selecionar e distribuir ofertas de marketplaces brasileiros com monetização por links de afiliados.

O produto deve iniciar com operação local, baixo custo e fluxo ponta a ponta funcional:

```text
coletar ofertas -> normalizar -> persistir -> selecionar -> gerar mensagem -> enviar no WhatsApp -> registrar histórico
```

O backend principal será Django. O serviço auxiliar Node.js existente em `wa_service/` deve ser preservado e usado para envio no WhatsApp via Baileys. O banco obrigatório é SQLite em `data/descontos_bot.db`, com WAL e `foreign_keys=ON`.

## 2. Objetivos de Negócio

### Objetivo principal

Automatizar a curadoria e distribuição de ofertas para gerar receita recorrente por afiliados, começando por Amazon e Mercado Livre.

### Objetivos específicos

- Reduzir trabalho manual na busca e publicação de promoções.
- Evitar repostagens duplicadas no WhatsApp.
- Criar base histórica de ofertas, preços, execuções e envios.
- Operar localmente sem Docker e sem infraestrutura cloud no MVP.
- Preparar a arquitetura para novos marketplaces, painel operacional e IA.

## 3. Escopo

### MVP

- Scraping de Mercado Livre e Amazon usando os scrapers existentes em `scrapers/`.
- Coleta de até 5 páginas por marketplace.
- Normalização de título, preço atual, preço original, desconto, URL, marketplace, imagem e identificador externo.
- Persistência em SQLite.
- Seleção de ofertas ainda não enviadas, priorizadas por maior desconto.
- Envio de até 10 ofertas por ciclo para WhatsApp.
- Integração com `wa_service/`.
- Scheduler local com intervalo randômico entre 90 e 180 minutos.
- Bloqueio obrigatório de distribuição entre 00:00 e 06:00 BRT.
- Modo `dry_run`.
- Django Admin mínimo para operação.

### Fora do MVP

- Docker, Docker Compose ou runtime equivalente.
- FastAPI, Uvicorn, SQLAlchemy e Jinja2.
- Banco diferente de SQLite.
- Suíte de testes automatizados como entregável.
- Deploy em produção.
- Instagram, Telegram e multiusuário.
- IA para recomendação ou geração avançada.
- Painel customizado completo.

### Futuro

- Shopee, Netshoes e Centauro.
- Dashboard operacional com base em `design_system/refs/design_system.html`.
- Geração e validação de links de afiliado por marketplace.
- Histórico de preço.
- Score de qualidade com IA.
- Segmentação por categoria e canal.
- Métricas de clique, conversão e receita.

## 4. Personas e Casos de Uso

### Persona principal — Operador afiliado

Administra grupos de ofertas e precisa publicar promoções com consistência sem gastar horas procurando produtos.

Necessidades:

- Encontrar boas ofertas.
- Evitar duplicidade.
- Manter grupos ativos.
- Usar links monetizáveis.
- Auditar o que foi enviado.

### Persona futura — Administrador de campanhas

Configura marketplaces, canais, limites, horários, categorias e regras de monetização.

### Casos de uso

- UC01: coletar ofertas automaticamente.
- UC02: selecionar ofertas com maior desconto.
- UC03: impedir reenvio de ofertas já entregues.
- UC04: enviar até 10 ofertas por ciclo no WhatsApp.
- UC05: registrar histórico de scraping e distribuição.
- UC06: operar em `dry_run` antes de ativar envios reais.
- UC07: evoluir score e copy com IA futuramente.

## 5. Arquitetura do Sistema

### Alto nível

```text
Scheduler local
  -> Orquestração Django
    -> Scrapers Mercado Livre/Amazon
    -> Normalização
    -> SQLite
    -> Seleção e ranking
    -> Geração de conteúdo
    -> wa_service Node.js
    -> WhatsApp
```

### Estrutura alvo

```text
apps/
  _base/
    models.py
  marketplaces/
    models.py
    admin.py
  offers/
    models.py
    admin.py
    services/
      normalizer.py
      repository.py
  scraping/
    management/commands/scrape_marketplace.py
    services/
      runner.py
      adapters.py
  curation/
    services/
      selector.py
      message_builder.py
  distribution/
    models.py
    admin.py
    services/
      whatsapp_client.py
  orchestration/
    management/commands/run_bot.py
    services/
      scheduler.py
      execution_window.py
```

O serviço `wa_service/` permanece como processo Node.js auxiliar. O Django não deve portar a lógica interna do Baileys; deve apenas chamar um contrato HTTP/local bem definido.

## 6. Domínios e Responsabilidades

### Scraping

Coleta dados dos marketplaces, usa sessão HTTP persistente, headers realistas, delays conservadores e detecção de CAPTCHA.

Não decide envio, não monta mensagem e não grava regras de distribuição.

### Offers

Normaliza, persiste, atualiza e deduplica ofertas. Mantém `first_seen_at`, `last_seen_at`, hash estável e payload bruto.

### Curation

Filtra ofertas elegíveis e calcula ranking inicial por desconto.

### Content

Gera mensagens em pt-BR para WhatsApp com preço, desconto e link final.

### Distribution

Envia mensagens via `wa_service/`, registra sucesso/falha e preserva a mensagem enviada.

### Orchestration

Coordena o ciclo completo, respeita janela de silêncio, registra execução e aplica intervalos randômicos.

## 7. Fluxos Funcionais

### Ciclo completo

```text
Início
  -> Verificar horário BRT
  -> Se 00:00-06:00, dormir até a janela permitida
  -> Criar execução
  -> Executar scrapers ativos
  -> Normalizar ofertas
  -> Salvar ou atualizar ofertas
  -> Selecionar ofertas elegíveis
  -> Gerar mensagens
  -> Enviar via WhatsApp ou simular em dry_run
  -> Registrar entregas
  -> Fechar execução
  -> Dormir 90-180 minutos
```

### Seleção

```text
Ofertas ativas
  -> remover já entregues no canal
  -> remover inválidas
  -> aplicar desconto mínimo
  -> ordenar por desconto desc
  -> limitar a 10
```

### Envio

```text
Oferta selecionada
  -> montar mensagem
  -> escolher affiliate_url ou product_url
  -> enviar para wa_service
  -> registrar Delivery sent/failed/skipped
  -> aguardar intervalo entre mensagens
```

## 8. Modelagem de Dados

Todas as tabelas de domínio devem herdar `apps._base.models.TimestampedModel`.

### Marketplace

- `id`
- `name`
- `code`
- `base_url`
- `is_active`
- `affiliate_enabled`
- `created_at`
- `updated_at`

### Offer

- `id`
- `marketplace_id`
- `external_id`
- `title`
- `normalized_title`
- `offer_hash`
- `current_price`
- `original_price`
- `discount_pct`
- `product_url`
- `affiliate_url`
- `image_url`
- `is_active`
- `raw_payload`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

### SocialChannel

- `id`
- `name`
- `code`
- `channel_type`
- `target`
- `is_enabled`
- `created_at`
- `updated_at`

### Delivery

- `id`
- `offer_id`
- `social_channel_id`
- `message`
- `delivery_status`
- `external_message_id`
- `error_message`
- `sent_at`
- `created_at`
- `updated_at`

Regra obrigatória futura/imediata:

```text
UNIQUE (offer_id, social_channel_id)
```

### ScrapingRun

- `id`
- `marketplace_id`
- `started_at`
- `finished_at`
- `status`
- `total_collected`
- `total_valid`
- `error_message`
- `created_at`
- `updated_at`

### Setting

- `id`
- `key`
- `value`
- `description`
- `created_at`
- `updated_at`

## 9. Estratégia de Scraping

### Regras gerais

- Usar `requests.Session`.
- Usar headers compatíveis com navegador real.
- Aplicar delay conservador entre páginas.
- Coletar no máximo 5 páginas por ciclo.
- Detectar CAPTCHA, bloqueio ou HTML vazio e registrar falha.
- Não executar concorrência agressiva.

### Mercado Livre

Usar `scrapers/mercado_livre.py` como ativo inicial. Deve extrair título, preço atual, preço original, desconto, link, imagem e identificador do produto quando possível.

### Amazon

Usar `scrapers/amazon.py` como ativo inicial. Deve ser mais conservador por risco maior de anti-bot. ASIN deve ser usado como `external_id` quando disponível.

### Marketplaces futuros

Shopee, Netshoes e Centauro entram somente após o MVP, cada um com adapter e normalizador próprio.

## 10. Algoritmo de Seleção de Ofertas

### MVP

```text
score = discount_pct
```

Critérios obrigatórios:

- Oferta ativa.
- Marketplace ativo.
- Título preenchido.
- URL preenchida.
- `current_price > 0`.
- `discount_pct > 0`.
- Oferta ainda sem `Delivery` bem-sucedido no canal.
- Limite de 10 ofertas por ciclo.

Regra recomendada para qualidade mínima:

```text
discount_pct >= 20 OR absolute_saving >= 50.00
```

## 11. Geração de Conteúdo

Mensagem oficial enviada para canais privados de WhatsApp, herdada de `post_generator.py` e implementada em `apps/curation/services/message_builder.py`:

```text
📦 *{title}*

{badge}
━━━━━━━━━━━━━━━━━━━━━

💰 ~De {original_price}~
✅ *Por apenas {current_price}*
🏷️ *{discount_pct}% OFF*

🛒 Compre aqui 👇
{final_url}

⏰ Oferta por tempo limitado!
━━━━━━━━━━━━━━━━━━━━━
🤖 @descontos.bot
```

Regras:

- Texto em pt-BR.
- Badge variável por intensidade do desconto: `🚨 *OFERTA IMPERDÍVEL* 🚨` quando `discount_pct >= 50`; `🔥 *ALERTA DO BOT* 🔥` quando `discount_pct >= 30`; `⚡ *BOT ACHOU DESCONTO* ⚡` no demais.
- Título encurtado para 80 caracteres com `textwrap.shorten`.
- `final_url` segue `link_strategy` do canal: `bridge_url` para grupos privados (Amazon), `affiliate_link` direto para canais aprovados (Instagram, canal público de WhatsApp, site).
- Linguagem proibida da seção 21.2.7 deve ser respeitada em qualquer canal.
- Mensagem enviada deve ser preservada em `Delivery.message`.

## 12. Integração com Redes Sociais

### WhatsApp

Canal único do MVP. O Django chama `wa_service/` e recebe status estruturado.

Contrato mínimo:

```json
{
  "destination": "grupo-ou-jid",
  "message": "texto da mensagem"
}
```

Resposta:

```json
{
  "success": true,
  "message_id": "abc123",
  "sent_at": "2026-04-29T10:30:00-03:00"
}
```

## 13. Orquestração e Agendamento

Regras:

- Intervalo randômico entre 90 e 180 minutos.
- Nenhuma distribuição entre 00:00 e 06:00 BRT.
- Scraping pode ser bloqueado junto com distribuição para reduzir risco operacional.
- Falha em um scraper não derruba o ciclo.
- Falha crítica no WhatsApp interrompe apenas a etapa de envio.

## 14. Regras de Negócio

- Oferta repetida atualiza `last_seen_at`.
- Oferta enviada com sucesso não é reenviada para o mesmo canal.
- Envio com erro não conta como envio bem-sucedido.
- Credenciais ficam em `.env`.
- Sessões WhatsApp, bancos SQLite e logs locais não devem ser versionados.
- `dry_run` coleta, seleciona e monta mensagens, mas não envia.

## 15. Requisitos Não Funcionais

- Python 3.11+ e Django 6.0.4.
- Node.js 20 LTS.
- SQLite exclusivamente em `data/descontos_bot.db`.
- WAL e `foreign_keys=ON`.
- Logs operacionais suficientes para auditar ciclos.
- Código em inglês; UI, verbose names e documentação operacional em pt-BR.
- Sem testes automatizados como entregável do MVP, mas com verificação manual e comandos Django.

## 16. Estratégia Anti-Bloqueio

- Execução local em rede residencial.
- Delays entre páginas.
- Retry com backoff.
- Baixa frequência.
- Limite de páginas.
- Headers realistas.
- Detecção de CAPTCHA.
- Registro de falhas por marketplace.

## 17. Roadmap Evolutivo

### Fase 1 — Estabilização técnica

Alinhar Django, banco, apps, settings e orquestrador ao padrão alvo.

### Fase 2 — MVP local

Scraping, normalização, seleção, WhatsApp, histórico e scheduler.

### Fase 3 — Operação mínima

Django Admin, configurações, dry_run, checklist e logs.

### Fase 4 — Afiliados

Geração de links finais e validação por marketplace.

### Fase 5 — Novos marketplaces

Shopee, Netshoes e Centauro.

### Fase 6 — Inteligência

Score avançado, histórico de preço e IA.

## 18. Riscos e Mitigações

- Bloqueio de marketplace: reduzir frequência, detectar CAPTCHA e usar delays.
- Bloqueio WhatsApp: limitar mensagens, evitar spam e respeitar janela de silêncio.
- Divergência entre PRD e código atual: sprint inicial de estabilização.
- SQLite crescer demais: manter modelagem simples e índices úteis.
- Links de afiliado ausentes: permitir envio de link original por configuração explícita.

## 19. Métricas de Sucesso

### MVP

- 50+ ofertas coletadas por ciclo quando os marketplaces responderem.
- 30+ ofertas válidas por ciclo.
- Até 10 ofertas enviadas por ciclo.
- 0 duplicidades de envio por canal.
- Taxa de falha de scraping abaixo de 20%.
- Erros de envio WhatsApp abaixo de 10% por ciclo.

### Futuro

- CTR por oferta.
- Conversão por marketplace.
- Receita por grupo.
- Receita por categoria.
- Melhor horário de envio.

## 20. Melhorias Propostas

- Criar `offer_hash` para deduplicação estável.
- Criar blacklist de termos como usado, reembalado, avariado e sem garantia.
- Criar histórico de preço após MVP.
- Criar painel customizado somente depois do Admin validar a operação.
- Criar score mínimo antes de aumentar volume.
- Adicionar checklist operacional por sprint.

## 21. Programa Amazon Associates — Compliance e Aprovação

### 21.1. Contexto

A conta Amazon Associates do projeto foi reprovada em revisão anterior. Esta seção cobre o trabalho contínuo de adequação às regras do programa para destravar a aprovação. A tag oficial de afiliado é `descontos.bot-20`.

A diretiva guia desta seção é: **o projeto está em produção e não pode parar de funcionar em nenhum momento**. Toda mudança aqui descrita é aditiva e respeita a operação atual (scraping ativo, ciclo de envio WhatsApp, ofertas no banco SQLite).

### 21.2. Política Amazon — regras invioláveis

Cada regra abaixo é tratada como invariante do sistema. Violação derruba a Fase 7 (compliance check) e bloqueia release.

1. **Disclosure obrigatório**: toda página com link de afiliado exibe *"Como Associado da Amazon, ganho por compras qualificadas"* próximo ao primeiro link e no rodapé.
2. **URL canônica**: `amazon.com.br/dp/<ASIN>?tag=descontos.bot-20`. Nunca URLs de busca, nunca sem tag, nunca tag de outra conta.
3. **Preço com timestamp**: todo preço exibido tem rótulo "Preço coletado em DD/MM/AAAA HH:mm".
4. **Sem mimetismo**: site não usa cor laranja Amazon, não usa logo Amazon como decoração, não imita layout. Apenas imagens dos produtos vindas do scraping.
5. **Conteúdo original**: cada `/oferta/<slug>` tem texto descritivo escrito por nós em pt-BR. Nunca copiar literal da Amazon.
6. **Grupo fechado nunca recebe afiliado direto**: apenas `bridge_url`.
7. **Linguagem proibida em qualquer canal**: "compre aqui e ganhe desconto exclusivo", "cashback", "doação por compra", "favorite este link", "cupom exclusivo Amazon", "imitação", "réplica".
8. **Categoria perigosa**: o site não pode parecer um "site só de cupons". Cada página de oferta precisa de conteúdo real, não apenas card + botão.

### 21.3. Modelo de canais e roteamento de link

Canais sociais ganham um campo `link_strategy` com dois valores:

- `affiliate_direct`: canais aprovados pela Amazon (site público, Instagram, Canal WhatsApp registrado no portal). Recebem `affiliate_link` direto.
- `bridge_only`: canais privados (grupos de WhatsApp, e-mail, qualquer canal não cadastrado no portal). Recebem `bridge_url` (link público para `/oferta/<slug>` no site).

Canal WhatsApp grupo é sempre `bridge_only`. O default seguro do campo é `bridge_only`.

`SocialChannel.channel_type` ganha duas variantes adicionais (`whatsapp_group`, `whatsapp_channel`) preservando o valor atual `whatsapp` para compatibilidade durante a migração.

### 21.4. Site público como funil rastreável

`https://descontos-bot.vercel.app` deixa de ser um redirecionador opcional e passa a ser o funil oficial de tráfego rastreável. O site estático fica integrado no repo principal `https://github.com/marcelopio10/descontos_bot.git`, no diretório `site/`.

Fluxo de publicação (Padrão A — git push):

1. Django gera `offers.json` em `apps/offers/services/site_publisher.py`.
2. Comando `python manage.py publish_offers --push` atualiza `site/offers.json`, commita e faz push no repo integrado.
3. Vercel detecta o push e auto-deploya.

Estrutura de páginas:

| Rota | Conteúdo |
|---|---|
| `/` | Home com cards de oferta consumindo `offers.json`. |
| `/oferta?slug=<slug>` | Página individual com 8 elementos obrigatórios (título, imagem, disclosure, preço com timestamp, desconto, descrição original, CTA com `rel="sponsored nofollow noopener"`, disclosure rodapé). Implementação inicial via query string para reduzir custo de SEO antes da aprovação. |
| `/r?slug=<slug>` | Bridge de redirect automático para grupos privados (Amazon). Resolve a oferta em `offers.json`, exibe disclosure brevemente e redireciona via `window.location.replace` para `affiliate_link`. Fallback `<meta http-equiv="refresh">`. NÃO substitui `/oferta` — esta é exclusiva do funil WhatsApp privado. |
| `/links` | Linktree próprio para a bio do Instagram, consome `links.json`. |
| `/sobre` | Sobre o projeto. |
| `/disclosure` | Texto completo do disclosure. |

### 21.5. Engine de posts Instagram

Novo app `apps/social_posts` com modelo `InstagramPost` e geradores para os 4 formatos do Instagram (feed, carousel, story, reel). Cada gerador produz assets PNG rasterizados, com imagem do produto embutida e sem QR Code, e caption em pt-BR; postagem é manual para evitar derrubada da conta.

Links de UTM padronizado a partir de `apps/social_posts/services/link_builder.py`:

```
Offer.affiliate_link + ?utm_source=instagram&utm_medium={bio|story|reel|carousel_link}&utm_campaign=offer_<id>
```

Instagram é canal aprovado para afiliado direto. Bio e stories usam links gerados a partir de `Offer.affiliate_link`; redirect via `bridge_url` é obrigatório apenas para canais privados, como grupos de WhatsApp. A geração é automática; a postagem fica manual.

### 21.6. Compliance check automatizado

`scripts/amazon_compliance_check.py` valida em runtime:

- Home responde HTTP 200, tem disclosure visível e nenhum texto proibido.
- `offers.json` responde HTTP 200, tem disclosure, lista de ofertas e cada link Amazon contém `tag=descontos.bot-20` (ou é `amzn.to`/`amzlink.to`).
- `/oferta.html?slug=<slug>` responde HTTP 200, tem disclosure e timestamp de preço renderizado pelo JavaScript do site.
- `/links.json` responde HTTP 200, tem disclosure, mínimo de 5 itens, todos com UTM rastreável.
- `/links` ou `/links.html` responde HTTP 200 e mostra disclosure.

O script é o gate da Fase 7 do plano de execução. Em vez de suíte de testes automatizados (proibida pelo `AGENTS.md`), o compliance check cumpre o papel de invariante verificável.

### 21.7. Tag de afiliado e variáveis

Variável canônica em `.env`: `AMAZON_ASSOCIATE_TAG=descontos.bot-20` (preservada — o scraper atual já depende dela). Em `core/settings.py`:

```python
PUBLIC_SITE_BASE_URL = os.environ.get("PUBLIC_SITE_BASE_URL", "https://descontos-bot.vercel.app")
AMAZON_AFFILIATE_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG", "descontos.bot-20")
```

Toda construção de URL Amazon passa por `Offer.affiliate_link`. Hierarquia: `affiliate_url_override` (manual `amzlink.to`/`amzn.to`) > `affiliate_url` existente (formato `sl2` populado pelo scraper) > URL `?tag=` montada a partir do ASIN > `product_url`.

### 21.8. Mitigação imediata de violação

`apps/curation/services/message_builder.py` enviava `affiliate_url` direto para o grupo de WhatsApp, violando a regra 6 da seção 21.2. A mitigação reativa o roteamento por canal e mantém o template oficial documentado na seção 11:

- Template oficial (seção 11) é o herdado de `post_generator.py`. Ele usa emojis, badge por intensidade e separador visual; não inclui nenhuma das frases proibidas pela regra 7 da seção 21.2.
- Roteamento passa a respeitar `link_strategy` de cada canal — grupo privado recebe `bridge_url`, nunca afiliado direto.

A mitigação só foi ativada após o site público passar a renderizar `/oferta?slug=…` lendo `offers.json`, para evitar janela em que o grupo recebesse link válido para uma página inexistente.

## 22. Changelog — Amazon Compliance

Cada fase de implementação registra aqui uma entrada datada (formato AAAA-MM-DD) com: o que foi adicionado, qual regra Amazon endereça, como verificar.

**Estado documentado:** Fases 0, 1, 2, 3, 4 e 5 concluídas em 2026-05-05. Fases 6 e 7 concluídas em 2026-05-06.

### 2026-05-05 · Pré-Fase 0 — git init + branch + abertura desta seção

- **O quê**: repositório git inicializado em `descontos.bot/`. Remote `origin` configurado para `github.com/marcelopio10/descontos_bot.git` (sem push). Branch `feat/amazon-compliance` criada a partir de `main`. Seções 21 e 22 adicionadas ao PRD.
- **Por quê**: regra de execução do plano exige rastreabilidade por commits atômicos por sub-passo. Sem git, sustentar gates por fase fica frágil.
- **Endereça**: nenhuma regra Amazon diretamente — fundação operacional do trabalho subsequente.
- **Como verificar**: `git status` vazio; `git log --oneline` mostra `baseline` + `docs(prd): add Amazon compliance sections`; `git branch --show-current` retorna `feat/amazon-compliance`.

### 2026-05-05 · Fase 0 — `docs/SITE_ARCHITECTURE.md`

- **O quê**: inspecionado o repositório do site Vercel (`descontos.bot-v0`) e documentado o estado em `docs/SITE_ARCHITECTURE.md`. Confirmado que o site é HTML/CSS/JS puro, **não consome JSON dinâmico hoje**, não tem `vercel.json` nem GitHub Actions. Mapeados textos proibidos pela regra 7 da seção 21.2 ("cupons exclusivos", "🔔 CADASTRE-SE GRÁTIS", "💰 ECONOMIZE AGORA", "Frete grátis"). Inconsistência identificada entre remote local (`descontos.bot.git`) e URL fornecida pelo PO (`bot-monitor-ml`) — pendente de resolução antes da Fase 3.
- **Por quê**: o plano Fase 0.2 exige localizar a "rotina antiga de push para Vercel". A inspeção mostrou que essa rotina **não existe** — site nunca foi alimentado por JSON. Logo, a Fase 3 desenha do zero, sem necessidade de manter compatibilidade com formato anterior. Documentar isso evita retrabalho e suposições erradas.
- **Endereça**: regras 1, 4 e 7 da seção 21.2 (mapa de violações atuais a corrigir na Fase 4). Não corrige nada por si só — habilita as próximas fases.
- **Como verificar**: `test -f docs/SITE_ARCHITECTURE.md`; `git log --oneline` mostra commit `docs(arch): document Vercel site state and gap analysis`.

### 2026-05-05 · Plano separado — `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`

- **O quê**: criado plano operacional separado para executar o compliance Amazon em fases bloqueantes. O documento consolida a diretiva de produção viva, a sequência Fase 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 7, a Fase 6 como paralela após Fase 1, os gates de aceite e a decisão MVP por `/oferta?slug=...`.
- **Por quê**: o prompt original enviado ao agente anterior não gerou um artefato separado. Sem esse roteiro, a Fase 1 ficaria ambígua e poderia ser confundida com o roadmap antigo do MVP.
- **Endereça**: rastreabilidade operacional das regras 1 a 8 da seção 21.2. Não altera runtime.
- **Como verificar**: `test -f docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`; `rg -n "Fase 1|Caminho crítico" docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`.

### 2026-05-05 · Fase 1 — modelagem de dados para compliance

- **O quê**: a Fase 1 adiciona suporte de banco para `slug`, `asin`, `affiliate_url_override`, `short_description`, `price_collected_at`, `link_strategy`, `affiliate_tag`, `PUBLIC_SITE_BASE_URL` e `AMAZON_AFFILIATE_TAG`. As mudanças são aditivas e não ativam o roteamento por `bridge_url` no envio.
- **Por quê**: o banco precisa carregar os dados necessários para URL canônica, página pública de oferta, descrição original e estratégia de canal antes de publicar `offers.json` ou alterar mensagens.
- **Endereça**: regras 2, 3, 5 e 6 da seção 21.2. Regras 1, 4, 7 e 8 serão efetivadas no site e no compliance check das fases seguintes.
- **Como verificar**: `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`; shell assert da Fase 1 em `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`.

### 2026-05-05 · Fase 2 — ASIN no scraper e normalização Amazon

- **O quê**: a Fase 2 garante que novas ofertas Amazon sejam normalizadas com `asin`, `external_id` canônico igual ao ASIN e `price_collected_at`. Ofertas Amazon sem ASIN passam a ser rejeitadas no pipeline com log operacional claro, sem derrubar o ciclo.
- **Por quê**: a Fase 1 corrigiu a base existente por backfill, mas a ingestão futura precisa nascer compliance. Sem ASIN não há URL canônica `amazon.com.br/dp/<ASIN>?tag=descontos.bot-20`.
- **Endereça**: regra 2 da seção 21.2 e prepara a regra 3 para o `offers.json`/site.
- **Como verificar**: `python3 manage.py check`; `python3 manage.py scrape_marketplace amazon --max-pages 1`; shell assert de que não existem ofertas Amazon persistidas com `asin=''`.

### 2026-05-05 · Fase 3 — geração de `offers.json`

- **O quê**: a Fase 3 cria `apps/offers/services/site_publisher.py` e o comando `python3 manage.py publish_offers`, que gera `offers.json` versão `2.0` com disclosure, ofertas publicáveis, links afiliados canônicos, `detail_url` por `/oferta?slug=...` e timestamp de preço.
- **Por quê**: o site Vercel precisa de um payload estático e verificável antes da Fase 4 renderizar home e páginas de oferta. O modo padrão grava localmente em `data/exports/offers.json`; `--push` fica explícito para evitar deploy acidental.
- **Endereça**: regras 1, 2 e 3 da seção 21.2 no payload publicado, preparando a renderização das regras 4, 5, 7 e 8 no site.
- **Como verificar**: `python3 manage.py publish_offers --output=/tmp/offers.json`; shell assert da Fase 3 em `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`; `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`.

### 2026-05-05 · Fase 4 — site Vercel consumindo `offers.json`

- **O quê**: a Fase 4 substitui a home promocional do repo Vercel por site estático HTML/CSS/JS baseado no design system oficial (`design_system/refs/design_system.html`), consome `offers.json`, cria `/oferta.html?slug=...`, `/links.html`, `/sobre.html` e `/disclosure.html`, exibe disclosure na home, na página de oferta e no rodapé, e usa CTAs com `rel="sponsored nofollow noopener"`. Na home, cada card oferece dois caminhos: ver detalhes no site ou ir direto ao marketplace.
- **Por quê**: canais privados só podem ser roteados para `bridge_url` depois que a página pública de oferta existir e carregar os dados da oferta com preço, timestamp e disclosure.
- **Endereça**: regras 1, 2, 3, 4, 7 e 8 da seção 21.2; prepara a regra 6 para a Fase 5. A regra 5 usa fallback neutro quando `short_description` ainda está vazio.
- **Como verificar**: servir `site/` localmente; abrir `/`, `/oferta.html?slug=<slug>`, `/links.html`, `/sobre.html` e `/disclosure.html`; confirmar cards, disclosure, timestamp, CTA patrocinado e ausência de linguagem proibida.

### 2026-05-05 · Integração do site no repo principal

- **O quê**: o site estático antes mantido no clone `descontos.bot-v0` foi integrado em `site/` dentro de `descontos_bot.git`. O publisher passa a usar `SITE_PUBLIC_DIR=site` e `SITE_REPO_LOCAL_PATH=.` por padrão. O Vercel deve usar Root Directory `site/`, onde `vercel.json` mantém `/oferta`, `/links`, `/sobre` e `/disclosure`.
- **Por quê**: manter site e backend no mesmo repositório reduz risco operacional, evita sincronização manual entre remotes e simplifica o deploy Vercel do MVP.
- **Endereça**: operacionalização das Fases 3 e 4 no mesmo fluxo de versionamento.
- **Como verificar**: `python3 manage.py publish_offers --output=/tmp/offers.json`; servir `site/` localmente; conferir `site/offers.json`, home e página de oferta.

### 2026-05-05 · Fase 5 — roteamento por canal

- **O quê**: a Fase 5 altera o builder de mensagens para receber o canal social, usar o template neutro do PRD e escolher o link final por `SocialChannel.link_strategy`: `affiliate_direct` recebe `Offer.affiliate_link`; qualquer outro valor recebe `Offer.bridge_url`.
- **Por quê**: grupos privados de WhatsApp não podem receber afiliado direto. Após a Fase 4, o site público já possui página de oferta funcional para servir como ponte segura.
- **Endereça**: regras 6 e 7 da seção 21.2, mantendo a regra 2 para canais aprovados.
- **Como verificar**: `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`; shell assert da Fase 5 em `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`.

### 2026-05-06 · Fase 6 — engine de posts Instagram

- **O quê**: criada `apps/social_posts` com modelo `InstagramPost`, admin, serviços de legenda, links rastreados, renderização de assets e publicação de links da bio. Os comandos `generate_instagram_post`, `generate_instagram_carousel`, `generate_instagram_story` e `publish_bio_link` geram material para postagem manual, sem automatizar o Instagram.
- **Por quê**: Instagram precisa gerar tráfego rastreável direto `instagram -> Amazon` sem depender de envio automático, preservando compliance e operação manual.
- **Endereça**: rastreabilidade por UTM para tráfego Instagram usando `Offer.affiliate_link` direto. `Offer.bridge_url` continua reservado a canais privados como grupos de WhatsApp. Os assets respeitam `design_system/refs/design_system.html` como identidade visual oficial.
- **Como verificar**: comandos de aceite da Fase 6 em `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`; `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`.

### 2026-05-06 · Fase 7 — compliance final

- **O quê**: criado `scripts/amazon_compliance_check.py` como gate manual de compliance Amazon; `publish_bio_link` passou a incluir disclosure em `site/links.json`; `docs/CHECKLIST_PRE_MERGE.md` ganhou seção específica de Amazon Associates.
- **Por quê**: antes de solicitar nova revisão Amazon, o projeto precisa validar de forma reprodutível home, `offers.json`, página de oferta, `links.json` e `/links` contra as regras invioláveis da seção 21.2.
- **Endereça**: regras 1, 2, 3 e 7 da seção 21.2 como checks automatizados; mantém as regras 4, 5, 6 e 8 cobertas pelas fases anteriores e pelo checklist humano pré-revisão.
- **Como verificar**: `python3 scripts/amazon_compliance_check.py`; `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`.

### 2026-05-07 · Ajuste final das Fases 5 e 6

- **O quê**: confirmada a tag canônica `descontos.bot-20`; defaults, documentação, checklist e exports do site foram alinhados. O builder de mensagens passou a usar o template neutro do PRD para canais privados e a engine Instagram passou a gerar posts e links de bio apenas com ofertas Amazon publicáveis.
- **Por quê**: finalizar o roteamento seguro por canal e garantir que Instagram gere tráfego rastreável `instagram -> Amazon` com `tag=descontos.bot-20`.
- **Endereça**: regras 2, 6 e 7 da seção 21.2 e o critério de aceite da Fase 6.
- **Como verificar**: gates das Fases 5 e 6 em `docs/AMAZON_COMPLIANCE_EXECUTION_PLAN.md`; `python3 scripts/amazon_compliance_check.py`; `python3 manage.py check`; `python3 manage.py makemigrations --dry-run`.

### 2026-05-07 · Fase 7 — reforço do gate HTTP local

- **O quê**: `scripts/amazon_compliance_check.py` passou a subir um servidor HTTP local temporário para validar `site/` por status 200 e conteúdo, cobrindo home, `offers.json`, `/oferta.html?slug=...`, `links.json` e `/links` ou `/links.html`.
- **Por quê**: alinhar o gate automatizado ao critério da Fase 7, que exige verificação de rotas públicas e não apenas leitura direta de arquivos.
- **Endereça**: regras 1, 2, 3 e 7 da seção 21.2 com checagens reprodutíveis antes de nova revisão Amazon.
- **Como verificar**: `python3 scripts/amazon_compliance_check.py`; saída esperada `ALL COMPLIANCE CHECKS PASSED`.

### 2026-05-08 · Fechamento de MVP — template oficial, slug universal e canal de homologação

- **O quê**:
  - Seção 11 do PRD e a Fase 5 do plano de execução adotam o template enriquecido derivado de `post_generator.py` como mensagem oficial. O template não contém nenhuma das frases proibidas pela regra 7 da seção 21.2.
  - `apps/offers/services/repository.py` passa a gerar `slug` automaticamente para toda oferta capturada, não apenas Amazon. `apps/curation/services/selector.py` exclui de canais `bridge_only` qualquer oferta sem `slug` para impedir bridge URL inválida.
  - `apps/offers/models.py` refina `affiliate_link`: respeita `affiliate_url` existente para Mercado Livre e para Amazon quando a URL já é compliance (`tag=descontos.bot-20`, `amzn.to`, `amzlink.to`). Sem cobertura, cai para a URL canônica por ASIN ou para `product_url`.
  - Novo canal `whatsapp_main` (homologação `descontos.bot - Homologação`) substitui `whatsapp_principal` como destino padrão de envio. Settings ganha `ALLOW_PRODUCTION_WHATSAPP_SEND` (default `false`); `run_bot` bloqueia envio real para o target de produção `descontos.bot` enquanto a flag estiver desligada.
  - `apps/offers/services/site_publisher.py` agora faz `git pull --ff-only origin <branch>` explícito antes de commitar para evitar fast-forward errado em branch não rastreada.
- **Por quê**: alinhar a documentação à decisão do PO de manter o template enriquecido (já validado em homologação) e fechar arestas operacionais antes de encerrar o MVP — slug universal viabiliza `bridge_url` para qualquer marketplace futuro, e o lock de produção evita envio acidental antes da liberação formal.
- **Endereça**: regras 2, 6 e 7 da seção 21.2 (template respeita linguagem proibida; `bridge_only` continua roteando para `bridge_url` válido; `affiliate_link` honra `tag=descontos.bot-20`).
- **Como verificar**:
  - `python3 manage.py check`
  - `python3 manage.py makemigrations --dry-run`
  - `python3 manage.py run_bot --dry-run --once --skip-scraping`
  - `python3 scripts/amazon_compliance_check.py`

### 2026-05-08 · Bridge auto-redirect para grupos WhatsApp

- **O quê**:
  - `Offer.bridge_url` passa a apontar para `/r?slug=<slug>` em vez de `/oferta?slug=<slug>`. A página `/oferta` segue intacta para navegação interna do site (cards do home).
  - Nova rota estática `site/r.html` (rewrite `/r` no `vercel.json`): lê `offers.json`, mostra disclosure por instantes e redireciona via `window.location.replace(affiliate_link)`. Fallback por `<meta http-equiv="refresh">` para navegadores sem JS.
  - `apps/curation/services/message_builder.py` ganha log estruturado `whatsapp_link_resolved` em `get_final_url`, com `route ∈ {affiliate_direct, affiliate_direct_non_public, bridge_redirect}` e `has_affiliate_tag` para auditoria.
  - `scripts/amazon_compliance_check.py` ganha `check_redirect_page` validando HTTP 200, disclosure visível, ausência de texto proibido, presença de `window.location.replace`, referência a `affiliate_link` e fallback `<meta http-equiv="refresh">`.
- **Por quê**: o usuário do grupo de WhatsApp clicava no link, abria a página `/oferta` e precisava clicar de novo no botão "Ver na loja" — segundo clique evitável que reduzia conversão. A bridge `/r` mantém compliance Amazon (página HTML real, com disclosure visível antes do redirect, link patrocinado preserva `tag=descontos.bot-20`) e elimina o atrito.
- **Endereça**: regras 2, 4, 6 e 7 da seção 21.2 (preserva tag canônica, não imita layout Amazon, segue `bridge_only` para grupos privados, mantém linguagem permitida).
- **Como verificar**:
  - `python3 manage.py check`
  - `python3 manage.py shell -c "from apps.offers.models import Offer; o = Offer.objects.exclude(slug='').first(); print(o.bridge_url)"` deve imprimir `https://descontos-bot.vercel.app/r?slug=<slug>`.
  - `python3 manage.py run_bot --dry-run --once --skip-scraping` — log `whatsapp_link_resolved` deve mostrar `route=bridge_redirect` para Amazon em canal `bridge_only`.
  - `python3 scripts/amazon_compliance_check.py` — deve passar com `ALL COMPLIANCE CHECKS PASSED`.
