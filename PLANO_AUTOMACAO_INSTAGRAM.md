# Plano Técnico de Implementação — Automação Oficial do Instagram

> Status: Sprint 5 (handoff manual via Telegram) entregue em 2026-06-03.
> Escopo original: salvar plano técnico (Cloudinary + Meta Graph direto). Implementação real adotou Composio CLI no Sprint 4 e, no Sprint 5, virou estratégia para **publicação manual com handoff por Telegram** — ver seções 2.bis e 2.ter abaixo.

## Atualização de execução (2026-06-03) — Sprint 5

A estratégia de automação total foi revertida. Decisão do PO: continuar publicando manualmente no app do Instagram (onde o link sticker do story funciona nativamente) ao invés de empurrar pela API. Volume é baixo (≤ 2 stories/dia) e o PO se organiza sozinho.

### 2.ter Handoff manual via Telegram

Componentes entregues:

```text
apps/social_posts/
  services/instagram_handoff_telegram.py        # deliver_post_to_handoff + mark_post_as_posted
  management/commands/discover_handoff_chat_id.py
  management/commands/telegram_handoff_listener.py
  migrations/0003_instagrampost_telegram_handoff_message_id_and_more.py
apps/distribution/services/telegram_client.py  # send_document, get_updates, answer_callback_query, edit_message_reply_markup
docs/HOWTO_HANDOFF_INSTAGRAM_TELEGRAM.md
```

Fluxo:

```text
generate_instagram_story
  → InstagramPost(status=ready)
  → deliver_post_to_handoff envia no DM Telegram do PO (PNG como document, caption pronta, URL do sticker em bloco destacado, botão inline "✅ Marcar como postado")
  → status=awaiting_post
  → PO posta manualmente no IG (cola URL no link sticker)
  → PO clica no botão "✅ Marcar como postado"
  → telegram_handoff_listener (daemon long-poll) recebe callback_query
  → mark_post_as_posted atualiza status=posted + edita botão pra "✅ Postado"
```

Pontos chave:

- Bot Telegram **dedicado** ao handoff (`INSTAGRAM_HANDOFF_BOT_TOKEN`), separado do bot de publicação em canais (`TELEGRAM_BOT_TOKEN`) e separado do Hermes — evita conflito de long-poll com outros consumers.
- Allowlist por `INSTAGRAM_HANDOFF_CHAT_ID` — só o PO consegue marcar.
- `INSTAGRAM_HANDOFF_QUIET_HOURS_BRT=22:00-08:00` (default): mensagens silenciosas dentro da janela noturna. Sistema **não** enforça horários de publicação — só evita acordar o PO.
- Caption ganha bloco CTA grupo em rotação WhatsApp/Telegram (paridade do total de posts).
- Fallback Admin: ação **"Marcar como postado manualmente"** atualiza DB e edita botão Telegram mesmo se o daemon estiver offline.
- Re-envio: ação **"Re-enviar pacote Telegram"** limpa `telegram_handoff_message_id` e dispara `deliver_post_to_handoff` de novo.
- Composio publisher do Sprint 4 continua disponível como fallback técnico — action renomeada para **"Publicar via Composio (modo manual/fallback)"**.

Novo status no `InstagramPost.Status`: `AWAITING_POST` (`awaiting_post`).
Novo campo: `telegram_handoff_message_id`.

Documentação operacional: `docs/HOWTO_HANDOFF_INSTAGRAM_TELEGRAM.md`.

### Itens arquivados (fora de escopo)

- Publicação totalmente automatizada por scheduler.
- Janelas de publicação enforçadas pelo sistema (viram apenas janela de silêncio de notificação).
- Hosting de mídia pública (Cloudinary) — não necessário, PO posta direto pelo app.
- Spike Meta Graph API direto para link sticker — não necessário, sticker é adicionado no app pelo PO.



## Atualização de execução (2026-06-03)

A implementação divergiu do plano original em dois pontos principais. Ambos foram validados em produção com publicação real bem-sucedida.

### 2.bis Caminho oficial via Composio CLI

Decisão revisada: usar Composio CLI como camada de abstração sobre a Instagram Graph API. Composio resolve simultaneamente:

- hospedagem temporária pública da mídia (substitui Cloudinary),
- autenticação Meta (token + permissões gerenciados pela conexão Composio),
- chamadas `INSTAGRAM_POST_IG_USER_MEDIA` (create container) e `INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH` (publish).

Conexão ativa: `instagram_midge-frieda`.

Implicações:

- Cloudinary não é mais dependência operacional.
- Não há `meta_graph_client.py` separado — a Graph API é consumida via subprocess `composio execute`.
- Guard de produção foi renomeado para `INSTAGRAM_PUBLISH_DRY_RUN` (default `false`). Para forçar dry-run, exportar `INSTAGRAM_PUBLISH_DRY_RUN=true`.

Componentes reais entregues:

```text
apps/social_posts/
  services/composio_publisher.py     # orquestra create container + publish + atualiza DB
  management/commands/publish_instagram_post.py  # comando --post-id + --dry-run
  migrations/0002_instagrampost_instagram_media_id_and_more.py
```

Modelo `InstagramPost` recebeu apenas dois campos novos nesta etapa (escopo mínimo):

- `instagram_media_id` (CharField, indexado) — ID retornado pela Meta.
- `published_error` (TextField) — última mensagem de erro operacional.

Demais campos do plano original (`external_container_id`, `published_url`, `publish_attempts`, `scheduled_for`, `media_public_url`) ficaram fora desta sprint. Serão reavaliados em Sprint 5 conforme necessidade real.

### Gotcha técnico — Composio file_uploadable

A tool `INSTAGRAM_POST_IG_USER_MEDIA` expõe dois campos `file_uploadable` (`image_file` + `video_file`). Por isso:

- A flag `--file <path>` falha com `Pass the target field explicitly with -d`.
- A sintaxe `@<path>` dentro do JSON `-d` também falha (CLI tenta abrir literalmente `@/path`).

Forma correta: passar o caminho como string pura na chave do field:

```json
{
  "ig_user_id": "...",
  "media_type": "STORIES",
  "image_file": "/tmp/arquivo.jpg"
}
```

O CLI detecta que o field é `file_uploadable`, sobe o arquivo para storage temporário e injeta a URL pública para a Meta buscar.

### Limitação Story link sticker

A tool atual não expõe campo de sticker URL clicável para stories. Tráfego de afiliado continua via bio link (`/links`). Caption do story não vira link clicável.

### Sprint 4 — DoD validado

- Post `#3952` publicado em 2026-06-03 via API oficial.
- `instagram_media_id=18097955294030410` (`container_id=18094318856090197`).
- Status no banco: `posted`, `posted_at` preenchido, sem erro.
- Compliance Amazon mantido na caption (disclosure + tag).



## 1. Objetivo

Automatizar a publicação de ofertas do `descontos.bot` no Instagram usando exclusivamente o caminho oficial da Meta: Instagram Graph API / Content Publishing API.

O objetivo é transformar os assets já gerados pelo módulo `apps/social_posts` em publicações reais no Instagram, com rastreabilidade, limites operacionais, compliance Amazon e proteção contra envio acidental em produção.

## 2. Decisões aprovadas

- Caminho oficial: Instagram Graph API / Content Publishing API.
- Proibido usar Selenium, Playwright, Appium, automação visual, emulador ou bot não oficial para publicar no Instagram.
- Hospedagem pública dos assets: Cloudinary.
- Volume inicial: 2 stories por dia.
- Guard de produção obrigatório: nenhuma publicação real sem variável explícita de liberação.
- Primeira meta validada: publicar 1 story via API oficial e registrar o `InstagramPost` como `posted` com identificador externo retornado pela Meta.
- Manter deploy local, sem Docker e sem cloud como runtime da aplicação.
- Manter SQLite exclusivamente em `data/descontos_bot.db`.
- Manter compliance Amazon, incluindo disclosure e `tag=desconto.bot-20`.

## 3. Contexto técnico atual

O projeto já possui:

- Django como backend principal.
- `wa_service/` em Node.js com Baileys para WhatsApp.
- SQLite em `data/descontos_bot.db`.
- Publicação operacional para WhatsApp e Telegram.
- Geração de assets para Instagram em `apps/social_posts`.
- `InstagramPost` com status e caminhos de assets.
- Link builder com UTMs para Instagram.
- Bio links publicados no site.

Gargalo identificado:

- Existem posts/assets de Instagram prontos, mas a publicação ainda é manual.
- O status `posted` não representa publicação automatizada pela API.

## 4. Arquitetura proposta

Fluxo alvo:

```text
Offer
  -> InstagramPost READY
  -> asset PNG gerado localmente
  -> upload para Cloudinary
  -> URL pública HTTPS
  -> Meta Graph API cria media container
  -> Meta Graph API publica container
  -> InstagramPost vira POSTED ou FAILED
  -> logs + auditoria + métricas
```

Novos componentes sugeridos:

```text
apps/social_posts/
  services/
    meta_graph_client.py
    instagram_media_host.py
    instagram_publisher.py
    instagram_publication_policy.py
  management/commands/
    check_instagram_auth.py
    publish_instagram.py
    upload_instagram_asset.py
```

Responsabilidades:

- `meta_graph_client.py`: encapsular chamadas HTTP para a Graph API.
- `instagram_media_host.py`: publicar imagem local no Cloudinary e retornar URL HTTPS.
- `instagram_publisher.py`: orquestrar upload, criação de container, publicação e atualização do banco.
- `instagram_publication_policy.py`: aplicar limites, janela de silêncio, frescor da oferta e segurança operacional.
- `publish_instagram.py`: comando operacional com dry-run e execução real protegida por guard.
- `check_instagram_auth.py`: validar token, conta e permissões antes de publicar.
- `upload_instagram_asset.py`: testar upload público sem publicar no Instagram.

## 5. Modelo de dados proposto

Adicionar campos ao modelo `InstagramPost`:

```text
external_post_id
external_container_id
published_url
publish_attempts
publish_error
published_at
scheduled_for
media_public_url
```

Fluxo de status proposto:

```text
ready -> publishing -> posted
ready -> publishing -> failed
failed -> ready, quando reenfileirado manualmente
ready -> skipped, quando rejeitado por política
```

Observações:

- `external_post_id` deve guardar o ID retornado pela Meta após publicação.
- `external_container_id` deve guardar o ID temporário do media container.
- `publish_error` deve registrar mensagem operacional em pt-BR, sem segredos.
- `publish_attempts` deve impedir loops infinitos.
- `media_public_url` deve guardar a URL HTTPS gerada pelo Cloudinary.

## 6. Variáveis de ambiente propostas

```env
INSTAGRAM_BUSINESS_ACCOUNT_ID=
META_ACCESS_TOKEN=
META_GRAPH_API_VERSION=v23.0
ALLOW_PRODUCTION_INSTAGRAM_SEND=false
INSTAGRAM_DAILY_LIMIT=2
INSTAGRAM_MIN_INTERVAL_MINUTES=360
INSTAGRAM_MEDIA_HOST=cloudinary
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
```

Regras:

- Valores reais nunca devem ser versionados.
- `.env.example` pode conter apenas nomes e placeholders.
- `ALLOW_PRODUCTION_INSTAGRAM_SEND` deve ser `false` por padrão.
- Publicação real deve falhar se o guard não estiver explicitamente habilitado.

## 7. Time e responsabilidades

### PO — Marcelo

Responsável por decisões de negócio, acessos e validação final.

Tarefas principais:

- Confirmar que a conta do Instagram é Business ou Creator.
- Confirmar conexão da conta Instagram com Página do Facebook.
- Criar ou validar app no Meta Developers.
- Gerar token de longa duração.
- Criar ou validar conta Cloudinary.
- Definir limite inicial: 2 stories/dia.
- Validar tom editorial, copy e compliance.
- Aprovar primeiro envio real.
- Acompanhar métricas iniciais de seguidores, cliques e membros em canais.

### Agente Back-end

Responsável por integração, banco, comandos e segurança operacional.

Tarefas principais:

- Ajustar modelo `InstagramPost`.
- Criar migrations.
- Implementar cliente Meta Graph API.
- Implementar integração Cloudinary.
- Implementar publisher com dry-run e guard de produção.
- Implementar política de publicação.
- Implementar logs e mensagens em pt-BR.
- Garantir que erros não gerem publicação duplicada.
- Garantir compliance Amazon antes da publicação.

### Agente Front-end

Responsável por assets, landing de links e experiência visual.

Tarefas principais:

- Validar dimensões dos assets de stories e feed.
- Ajustar legibilidade dos templates.
- Garantir contraste, hierarquia visual e CTA.
- Melhorar `/links` como hub de aquisição.
- Criar variações visuais para evitar repetição.
- Validar assets em mobile.

### Agente Comunicação e Social Media

Responsável por calendário editorial, copy e aquisição.

Tarefas principais:

- Definir calendário inicial de publicações.
- Criar legendas reutilizáveis.
- Criar CTAs por canal.
- Definir critérios editoriais de rejeição.
- Criar destaques do Instagram.
- Monitorar primeiros sinais de performance.
- Propor ajustes de linguagem.

## 8. Sprints

## Sprint 0 — Preparação de conta, acesso e decisão operacional

### Definição

Validar pré-requisitos externos antes de implementar código.

### Objetivo

Garantir que a conta Instagram está apta a publicar pela API oficial da Meta.

### Tarefas do PO

- Confirmar conta Business ou Creator.
- Confirmar conexão com Página do Facebook.
- Criar/verificar app no Meta Developers.
- Confirmar que o Instagram está autorizado como fonte no Amazon Associates, se aplicável.
- Criar ou validar conta Cloudinary.
- Gerar token de longa duração.
- Salvar credenciais somente no `.env` local.
- Confirmar volume inicial de 2 stories/dia.

### Tarefas Back-end

- Documentar permissões necessárias:
  - `instagram_basic`
  - `instagram_content_publish`
  - permissões de página exigidas pela Meta.
- Documentar fluxo para validar token.
- Preparar checklist de setup Meta.

### Tarefas Front-end

- Validar dimensões atuais:
  - Story: 1080x1920.
  - Feed: 1080x1080 ou 1080x1350.
- Verificar se o visual atual não usa linguagem agressiva ou enganosa.

### Tarefas Comunicação/Social Media

- Definir tom editorial inicial.
- Definir CTAs seguros.
- Definir critérios de rejeição manual.

### Testes manuais

- Abrir Meta Business Suite.
- Confirmar conexão Instagram + Página.
- Confirmar que o app Meta enxerga a conta correta.
- Confirmar que o token permite consulta básica da conta.

### Validação

- PO confirma pré-requisitos externos.
- Credenciais existem localmente e não foram versionadas.
- Cloudinary está pronto para upload.

### DoD

- Conta Meta pronta.
- Token de longa duração disponível localmente.
- Cloudinary configurado localmente.
- Nenhum segredo em Git.

## Sprint 1 — Modelagem e estados de publicação

### Definição

Preparar o banco e o admin para rastrear publicação automatizada.

### Objetivo

Transformar `InstagramPost` em uma fila publicável e auditável.

### Implementação Back-end

- Adicionar campos:
  - `external_post_id`
  - `external_container_id`
  - `published_url`
  - `publish_attempts`
  - `publish_error`
  - `published_at`
  - `scheduled_for`
  - `media_public_url`
- Atualizar choices de status, se necessário:
  - `ready`
  - `publishing`
  - `posted`
  - `failed`
  - `skipped`
- Atualizar admin com filtros por:
  - status
  - formato
  - data
  - erro
- Criar ação administrativa para reenfileirar posts `failed`.

### Implementação Front-end

- Revisar se assets gerados continuam compatíveis após mudanças de modelo.

### Comunicação/Social Media

- Definir regras editoriais de rejeição:
  - produto sensível.
  - preço suspeito.
  - imagem quebrada.
  - título ruim.
  - desconto pouco relevante.

### PO

- Validar os novos campos no Admin.
- Definir se posts antigos `ready` continuam elegíveis ou se devem ser filtrados por idade.

### Testes manuais

Comandos previstos para validação quando esta sprint for implementada:

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 manage.py generate_instagram_story --top 1
```

### Validação

- Admin exibe os novos campos.
- Post novo continua sendo gerado.
- `run_bot` não quebra.

### DoD

- Migration criada.
- `manage.py check` OK.
- `makemigrations --dry-run` sem pendências após migration.
- Nenhuma publicação real realizada.

## Sprint 2 — Hospedagem pública dos assets no Cloudinary

### Definição

Criar camada para transformar imagem local em URL pública HTTPS.

### Objetivo

Atender requisito obrigatório da Meta: a mídia precisa estar publicamente acessível.

### Implementação Back-end

- Criar `apps/social_posts/services/instagram_media_host.py`.
- Implementar provider Cloudinary.
- Criar interface simples:

```python
class InstagramMediaHost:
    def upload(self, local_path: str, public_name: str) -> str:
        ...
```

- Validar:
  - arquivo existe.
  - extensão permitida.
  - tamanho aceitável.
  - URL gerada é HTTPS.
  - URL pública retorna imagem.
- Criar comando:

```bash
python3 manage.py upload_instagram_asset --post-id <id> --dry-run
python3 manage.py upload_instagram_asset --post-id <id>
```

### Implementação Front-end

- Garantir que a imagem final não dependa de arquivos locais externos.
- Conferir contraste, preço, desconto, marketplace e CTA.

### Comunicação/Social Media

- Definir padrão de nomes públicos:

```text
descontos-bot/instagram/{format}/{post_id}-{offer_id}.png
```

### PO

- Validar uma URL pública gerada no navegador.
- Confirmar que a imagem abre fora do ambiente local.

### Testes manuais

Comandos previstos:

```bash
python3 manage.py generate_instagram_story --top 1
python3 manage.py upload_instagram_asset --post-id <id> --dry-run
python3 manage.py upload_instagram_asset --post-id <id>
```

### Validação

- URL pública HTTPS abre no navegador.
- URL não expõe credenciais.
- Imagem não é commitada no Git.

### DoD

- Upload Cloudinary funcional.
- Falha de upload não muda post para `posted`.
- Logs são claros.
- `.env.example` atualizado sem valores reais.

## Sprint 3 — Cliente Meta Graph API

### Definição

Criar camada isolada para comunicação com a Graph API.

### Objetivo

Validar autenticação, conta e criação de container em modo seguro.

### Implementação Back-end

- Criar `apps/social_posts/services/meta_graph_client.py`.
- Implementar métodos:

```python
get_account_info()
create_media_container()
publish_media_container()
get_container_status()
```

- Tratar erros:
  - token inválido.
  - permissão ausente.
  - conta incorreta.
  - mídia inacessível.
  - rate limit.
  - container ainda processando.
- Criar comando:

```bash
python3 manage.py check_instagram_auth
```

- Criar dry-run do publisher:

```bash
python3 manage.py publish_instagram --post-id <id> --dry-run
```

### Implementação Front-end

- Sem alteração obrigatória nesta sprint.

### Comunicação/Social Media

- Revisar captions geradas para primeiro lote.
- Validar se a copy está adequada para publicação real.

### PO

- Rodar ou acompanhar validação de `check_instagram_auth`.
- Confirmar que a conta exibida é a correta.

### Testes manuais

Comandos previstos:

```bash
python3 manage.py check_instagram_auth
python3 manage.py publish_instagram --post-id <id> --dry-run
```

### Validação

O dry-run deve mostrar:

- conta Instagram alvo.
- formato.
- asset local.
- URL pública, se existir.
- caption.
- link rastreado.
- indicação clara de que nenhum envio real foi realizado.

### DoD

- Cliente Meta funciona em leitura/diagnóstico.
- Nenhuma publicação real sem guard.
- Erros são apresentados em pt-BR para operador.

## Sprint 4 — Publicação real controlada

### Definição

Publicar o primeiro story real com proteção de produção.

### Objetivo

Cumprir a primeira meta validada: publicar 1 story via API oficial e registrar o post como `posted`.

### Implementação Back-end

- Criar `apps/social_posts/services/instagram_publisher.py`.
- Implementar fluxo:

```text
READY
  -> PUBLISHING
  -> upload Cloudinary
  -> create container
  -> wait/poll status
  -> publish
  -> POSTED
```

- Em erro:

```text
PUBLISHING -> FAILED
```

- Criar comando:

```bash
python3 manage.py publish_instagram --format story --limit 1 --dry-run
python3 manage.py publish_instagram --format story --limit 1
```

- Exigir guard:

```env
ALLOW_PRODUCTION_INSTAGRAM_SEND=true
```

- Regras obrigatórias:
  - Não publicar dentro da janela de silêncio 00:00-06:00 BRT.
  - Não publicar post já `posted`.
  - Não publicar oferta rejeitada.
  - Não publicar link Amazon sem `tag=desconto.bot-20`.
  - Não publicar se asset não tiver URL HTTPS válida.

### Implementação Front-end

- Ajustar template se a API rejeitar proporção ou se houver corte visual.
- Validar story em tela real de celular.

### Comunicação/Social Media

- Revisar primeiro story antes do envio.
- Confirmar que o CTA está adequado.
- Confirmar que não há promessa enganosa.

### PO

- Autorizar primeiro envio real.
- Validar story publicado no Instagram.
- Confirmar se status no banco foi atualizado corretamente.

### Testes manuais

Comandos previstos:

```bash
python3 manage.py publish_instagram --format story --limit 1 --dry-run
ALLOW_PRODUCTION_INSTAGRAM_SEND=true python3 manage.py publish_instagram --format story --limit 1
```

Consulta prevista:

```bash
python3 manage.py shell -c "from apps.social_posts.models import InstagramPost; print(list(InstagramPost.objects.values('id','status','external_post_id','published_at')[:5]))"
```

### Validação

- Story aparece no Instagram.
- `InstagramPost.status = posted`.
- `external_post_id` preenchido.
- `published_at` preenchido.
- Falha não marca como publicado.

### DoD

- 1 story real publicado pela API oficial.
- Guard obrigatório validado.
- Banco atualizado corretamente.
- Compliance Amazon continua passando.

## Sprint 5 — Fila, limites e scheduler seguro

### Definição

Automatizar rotina diária com limite e espaçamento.

### Objetivo

Publicar 2 stories/dia com segurança operacional.

### Implementação Back-end

- Criar `apps/social_posts/services/instagram_publication_policy.py`.
- Aplicar regras:
  - máximo de 2 stories/dia no início.
  - intervalo mínimo entre posts.
  - respeitar 00:00-06:00 BRT.
  - priorizar maior desconto/economia.
  - evitar repetição de oferta.
  - evitar oferta velha.
  - evitar marketplace repetido em sequência quando possível.
- Criar modo de execução pontual:

```bash
python3 manage.py publish_instagram --once --format story --limit 1
```

- Criar relatório simples:

```bash
python3 manage.py instagram_publication_report --days 7
```

### Implementação Front-end

- Criar variações visuais:
  - oferta única.
  - top desconto.
  - preço caiu.
  - achado do dia.

### Comunicação/Social Media

Calendário inicial aprovado:

```text
Story 1: manhã ou início da tarde.
Story 2: fim da tarde ou noite.
```

Evitar publicar entre 00:00 e 06:00 BRT.

### PO

- Acompanhar diariamente por 7 dias.
- Aprovar ou não aumento futuro de volume.

### Testes manuais

Comandos previstos:

```bash
python3 manage.py publish_instagram --format story --limit 2 --dry-run
ALLOW_PRODUCTION_INSTAGRAM_SEND=true python3 manage.py publish_instagram --format story --limit 1
```

### Validação

- Não publica mais de 2 stories/dia.
- Não publica dentro da janela de silêncio.
- Não repete oferta.
- Não interfere em WhatsApp/Telegram.

### DoD

- Rotina segura para 2 stories/dia.
- Logs auditáveis.
- Guard de produção ativo.
- Limite diário configurável.

## Sprint 6 — Funil de crescimento e rastreamento

### Definição

Conectar Instagram ao funil de aquisição do produto.

### Objetivo

Fazer as publicações gerarem tráfego para WhatsApp, Telegram e site.

### Implementação Back-end

- Padronizar UTMs:

```text
utm_source=instagram
utm_medium=story|feed|carousel|reel|bio
utm_campaign=offer_<id>
utm_content=<template|variant>
```

- Preparar modelo futuro de métricas, se necessário:

```text
SocialMetricSnapshot
ClickEvent
```

- Garantir que `/links.json` contenha:
  - WhatsApp.
  - Telegram.
  - Instagram.
  - site/ofertas.
  - disclosure.

### Implementação Front-end

- Melhorar `/links` como página de entrada mobile-first.
- Incluir CTAs:
  - Entrar no WhatsApp.
  - Entrar no Telegram.
  - Ver ofertas de hoje.
  - Seguir no Instagram.
- Incluir explicação curta:
  - como o bot funciona.
  - uso de links de afiliado.

### Comunicação/Social Media

- Criar 10 legendas reutilizáveis.
- Criar 5 CTAs por canal.
- Criar calendário editorial de 14 dias.
- Criar destaques:
  - Amazon.
  - Casa.
  - Tech.
  - Até R$50.
  - Como funciona.

### PO

- Aprovar copy da bio.
- Atualizar bio do Instagram com link do hub.
- Validar canais de entrada.

### Testes manuais

- Abrir `/links` no celular.
- Clicar WhatsApp.
- Clicar Telegram.
- Clicar oferta.
- Verificar disclosure.

### Validação

- Instagram aponta para hub próprio.
- CTAs estão funcionais.
- Links possuem UTM.
- Compliance segue válido.

### DoD

- `/links` funciona como hub real de aquisição.
- CTAs aprovados.
- Métrica mínima de origem preparada.

## Sprint 7 — Piloto operacional e rollout

### Definição

Rodar automação em produção com baixo volume e observação diária.

### Objetivo

Confirmar que o processo opera por vários dias sem trabalho manual obrigatório.

### Semana 1

- 2 stories/dia.
- Revisão diária do PO.
- Monitorar:
  - falhas Meta API.
  - posts duplicados.
  - alcance manual.
  - novos seguidores.
  - novos membros WhatsApp/Telegram.
  - cliques, quando disponível.

### Semana 2

- Manter 2 stories/dia.
- Avaliar se vale incluir feed/carrossel.
- Ajustar template e copy com base no desempenho.

### Tarefas Back-end

- Corrigir falhas de API.
- Ajustar logs.
- Refinar limites.
- Melhorar relatório semanal.

### Tarefas Front-end

- Ajustar templates com base em legibilidade e resposta do público.

### Tarefas Comunicação/Social Media

- Revisar tom.
- Criar novas variações de legenda.
- Organizar destaques no Instagram.

### Tarefas PO

- Revisar publicações diariamente.
- Registrar seguidores/membros por canal.
- Aprovar expansão futura.

### Testes manuais

- Conferir 10 stories publicados.
- Conferir links e CTAs.
- Conferir se nenhuma oferta expirou antes da publicação.
- Conferir se nenhuma publicação duplicou.

### Validação final

- 7 dias operando com 2 stories/dia.
- 0 posts duplicados.
- 0 posts fora da janela 00:00-06:00 BRT.
- 0 links Amazon sem tag correta.
- Redução clara do trabalho manual.
- Crescimento ou baseline mensurado por canal.

## 9. Critérios gerais de aceite

A automação só deve ser considerada pronta quando:

- Publicar via Instagram Graph API oficial.
- Não usar automação de navegador.
- Usar conta Business ou Creator.
- Usar Cloudinary para URL pública HTTPS dos assets.
- Exigir `ALLOW_PRODUCTION_INSTAGRAM_SEND=true` para publicação real.
- Respeitar janela de silêncio 00:00-06:00 BRT.
- Respeitar limite inicial de 2 stories/dia.
- Não publicar oferta duplicada.
- Não publicar oferta velha ou inválida.
- Registrar sucesso/falha no banco.
- Registrar ID externo retornado pela Meta.
- Manter compliance Amazon.
- Não quebrar WhatsApp ou Telegram.
- Permitir dry-run antes de envio real.
- Ter rollback simples: desligar o guard de produção.

## 10. Comandos de validação previstos para implementação futura

Não executar nesta etapa. Estes comandos são referência para quando a implementação começar.

```bash
python3 manage.py check
python3 manage.py makemigrations --dry-run
python3 scripts/amazon_compliance_check.py
python3 manage.py check_instagram_auth
python3 manage.py publish_instagram --format story --limit 1 --dry-run
```

Publicação real, somente após aprovação explícita e guard habilitado:

```bash
ALLOW_PRODUCTION_INSTAGRAM_SEND=true python3 manage.py publish_instagram --format story --limit 1
```

## 11. Atualizações documentais futuras

Após implementação ou início da sprint técnica, atualizar:

- `docs/PRD_DESCONTOS_BOT.md`
- `docs/HOWTO_PUBLICAR_OFERTAS_INSTAGRAM.md`
- `docs/CHECKLIST_PRE_MERGE.md`
- `.env.example`

Mudanças esperadas no PRD:

- Registrar Instagram automatizado como evolução aprovada.
- Substituir postagem manual como fluxo principal.
- Manter postagem manual como fallback.
- Adicionar Cloudinary como dependência operacional para mídia pública.
- Adicionar guard obrigatório de produção.
- Adicionar limite inicial de 2 stories/dia.
- Adicionar critérios de aceite e métricas.

## 12. Riscos e mitigação

### Risco: token Meta expirar ou perder permissão

Mitigação:

- Criar `check_instagram_auth`.
- Registrar erro claro.
- Não tentar publicar quando autenticação falhar.

### Risco: Meta rejeitar imagem

Mitigação:

- Validar proporção e tamanho antes do upload.
- Manter templates padronizados.
- Registrar erro e manter post como `failed`.

### Risco: duplicar publicação

Mitigação:

- Travar por status.
- Salvar `external_container_id` e `external_post_id`.
- Não republicar `posted`.
- Usar `publish_attempts`.

### Risco: publicação acidental em produção

Mitigação:

- `ALLOW_PRODUCTION_INSTAGRAM_SEND=false` por padrão.
- Dry-run como fluxo padrão de validação.
- Comando real deve falhar sem guard.

### Risco: ferir compliance Amazon

Mitigação:

- Validar `tag=desconto.bot-20`.
- Manter disclosure.
- Rodar compliance check antes de liberar.

### Risco: excesso de volume no Instagram

Mitigação:

- Começar com 2 stories/dia.
- Monitorar resposta da conta.
- Não se aproximar do limite da Meta no início.

## 13. Recomendação de execução

Sequência recomendada:

1. Concluir Sprint 0 com PO.
2. Implementar Sprint 1 e Sprint 2 sem publicar nada.
3. Validar Cloudinary com URL pública.
4. Implementar Sprint 3 com dry-run.
5. Executar Sprint 4 com 1 story real.
6. Rodar Sprint 5 com 2 stories/dia.
7. Só depois evoluir funil e métricas.

Próximo passo, quando autorizado:

- Atualizar `docs/PRD_DESCONTOS_BOT.md` com este plano aprovado.
- Iniciar Sprint 0 sem implementação de código.
