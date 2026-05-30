# Plano de Implementação — Poster do Telegram (@descontosbotlgm)

> Plano baseado no PRD `docs/PRD_DESCONTOS_BOT.md` (seções 6, 11, 12, 21.3) e na infraestrutura atual da branch `main` (estado em 2026-05-19). Sem código completo nesta etapa — apenas planejamento. Implementação virá em conversa posterior.

**Goal:** Publicar automaticamente no Telegram as mesmas ofertas elegíveis que vão para o WhatsApp, em **dois canais**:
- **Homologação:** `@descontosbothmg` (nome "descontos.bot - Homologacao") — recebe envios livremente para validar formato/links antes de produção.
- **Produção:** `@descontosbotlgm` (nome "descontos.bot") — só envia quando `ALLOW_PRODUCTION_TELEGRAM_SEND=true`.

Reutiliza 100% da camada de coleta, modelos, selector e janela de silêncio existentes, com compliance Amazon Associates.

**Architecture:** Novo módulo paralelo ao `whatsapp_client.py`/`delivery.py`. Telegram entra como mais um `SocialChannel` (`channel_type=telegram_channel`, `link_strategy=affiliate_direct`). Dois `SocialChannel` distintos: `telegram_homolog` e `telegram_main` — cada um com seu próprio `target` (chat_id) lido do `.env`. Reutiliza `Delivery` (a UNIQUE `(offer, social_channel)` já isola WhatsApp de Telegram homolog de Telegram prod). Dispatcher decide cliente por `channel.channel_type` e chat_id pelo `channel.target`. Um novo management command roda o ciclo Telegram de forma independente do `run_bot` para preservar 100% da lógica WhatsApp. Mesma semântica do WhatsApp (`whatsapp_main`=homolog, `whatsapp_principal`=prod), porém com nomes telegram explícitos: `telegram_homolog` e `telegram_main`.

**Tech Stack:** Django 6.0.4, Python 3.11+, `requests==2.32.3` (já no `requirements.txt`) chamando Bot API HTTPS diretamente — mesmo padrão minimalista do `whatsapp_client.py` (urllib). Sem libs novas pesadas.

---

## Step 1 — Discovery (mapa do projeto existente)

### Arquivos relevantes do poster do WhatsApp

| Arquivo | Papel |
|---|---|
| `apps/distribution/services/whatsapp_client.py` | Cliente HTTP para `wa_service/` (status + send_message). Padrão a replicar para Telegram. |
| `apps/distribution/services/delivery.py` | `deliver_offer_to_channel(offer, channel)` — monta msg, deduplica via `Delivery`, respeita silêncio, persiste resultado. |
| `apps/distribution/services/execution_window.py` | `is_distribution_silenced()` — janela 00:00–08:00 BRT (note: código diverge do PRD §13 que cita 00–06; manter o código como fonte da verdade). |
| `apps/distribution/models.py` | `SocialChannel` (com `ChannelType`, `LinkStrategy`) + `Delivery` (UNIQUE `offer + social_channel`). |
| `apps/distribution/admin.py` | Admin Django dos canais e entregas. |
| `apps/distribution/management/commands/seed_channels.py` | Seed dos canais WhatsApp; serve de molde para seed Telegram. |
| `apps/curation/services/message_builder.py` | `build_offer_message(offer, channel)` + `get_final_url(offer, channel)`. Roteia link por `link_strategy`. |
| `apps/curation/services/selector.py` | `select_offers_for_channel(channel, config)` — independente de canal; já filtra duplicados via `Delivery` por canal e exige `slug` em `bridge_only`. |
| `apps/orchestration/management/commands/run_bot.py` | Ciclo end-to-end: scraping → publish_offers → social_posts → WhatsApp delivery. Define `DEFAULT_CHANNEL_CODE='whatsapp_main'`. |
| `apps/orchestration/services/scheduler.py` | Sleep randômico 90–180 min, `wait_until_distribution_window()`. |

### Modelo de Oferta (`apps/offers/models.py::Offer`)

Campos usados pelo poster: `marketplace`, `title`, `current_price`, `original_price`, `discount_pct`, `product_url`, `affiliate_url`, `affiliate_url_override`, `image_url`, `slug`, `asin`, `short_description`, `price_collected_at`, `last_seen_at`, `is_active`.

Propriedades-chave já implementadas:
- `Offer.affiliate_link` — resolve URL Amazon com `tag=desconto.bot-20` (canonical ou `amzn.to`/`amzlink.to`). Para canais `affiliate_direct` o Telegram usa essa.
- `Offer.bridge_url` — `https://descontos-bot.vercel.app/r?slug=<slug>` (reservado a canais privados; não se aplica ao Telegram público).

### Agendamento atual

- **Não há Celery, nem cron interno explícito.** Loop é Python puro:
  - `python3 manage.py run_bot` entra em `while True: cycle; sleep(random 90–180 min)`.
  - `--once` roda 1 ciclo; `--dry-run` simula; `--skip-scraping` pula coleta.
  - O operador inicia esse processo manualmente (provavelmente via `tmux`/`nohup`).
- Não há agendador externo. Logo, o poster Telegram pode (a) rodar standalone com `python3 manage.py publish_telegram --once` em loop próprio, ou (b) ser disparado em sequência pelo mesmo loop do `run_bot` por wrapper shell. Plano oferece os dois caminhos sem mexer no `run_bot`.

### Formato de mensagem WhatsApp (referência — PRD §11)

```text
📦 *{title}*

{badge}
💰 ~De {original_price}~
✅ *Por apenas {current_price}*
🏷️ *{discount_pct}% OFF*

🛒 Compre aqui 👇
{final_url}

⏰ Oferta por tempo limitado!
━━━━━━━━━━━━━━━━━━━━━
🤖 @descontos.bot
```

Sintaxe usa o subset Markdown que o Baileys aceita para WhatsApp (`*bold*`, `~strike~`). Telegram não interpreta esse subset — converter para MarkdownV2 ou HTML (plano usa HTML por simplicidade — ver Step 4).

### Constatações que afetam o plano

1. **Reaproveito total da `Delivery`**: UNIQUE `(offer, social_channel)` garante que o mesmo `offer.id` enviado ao WhatsApp e ao Telegram cria dois registros distintos. Nenhuma migration de log nova é necessária.
2. **`SocialChannel.ChannelType` precisa de `telegram_channel`** — só tem variantes WhatsApp hoje.
3. **`SocialChannel.LinkStrategy` já é genérica** — o canal Telegram aprovado pela Amazon é `affiliate_direct`. Não precisa criar valor novo.
4. **Selector é channel-agnostic**: passar o canal Telegram retorna ofertas elegíveis exatamente como faz para WhatsApp.
5. **`message_builder` está acoplado a `*bold*`**. Construir um builder Telegram separado em vez de modificar o existente.

---

## Step 2 — Arquitetura proposta

### Princípio de separação

- **NÃO toca em** `apps/distribution/services/whatsapp_client.py`, `apps/distribution/services/delivery.py`, `apps/curation/services/message_builder.py`, `apps/orchestration/management/commands/run_bot.py`.
- Novo código mora todo em `apps/distribution/services/telegram_*.py` + `apps/curation/services/telegram_message_builder.py` + `apps/distribution/management/commands/publish_telegram.py`.

### Mapa de arquivos novos

| Caminho | Responsabilidade |
|---|---|
| `apps/distribution/services/telegram_client.py` | Cliente HTTP fino para Bot API. Métodos: `get_me()`, `send_photo(chat_id, photo_url, caption, reply_markup)`, `send_message(chat_id, text, reply_markup, disable_web_page_preview)`, `pin_chat_message(chat_id, message_id, disable_notification)`. Trata 429 com `retry_after`. Backoff exponencial em 5xx. |
| `apps/distribution/services/telegram_delivery.py` | `deliver_offer_to_telegram(offer, channel, client=None)` espelhando `delivery.py`: dedup por `Delivery`, respeita `is_distribution_silenced()`, persiste `Delivery` com status `sent/failed/skipped` e `external_message_id` (= `message_id` do Telegram). |
| `apps/distribution/services/telegram_rate_limiter.py` | `acquire(chat_id)` enforça 1 msg/seg por chat (com `time.monotonic`) + 30 msg/seg global. Single-process — não precisa Redis. |
| `apps/curation/services/telegram_message_builder.py` | `build_telegram_caption(offer)` em HTML, `build_telegram_inline_keyboard(offer, channel)`, `escape_html(text)`. |
| `apps/distribution/management/commands/publish_telegram.py` | Comando standalone: roda 1 ciclo de seleção+envio para um canal Telegram. Suporta `--dry-run`, `--once`, `--channel telegram_homolog` (default) ou `--channel telegram_main`, `--limit N`. Sem scraping (consome o que `run_bot` já populou). Bloqueia envio se `channel.code == 'telegram_main'` e `ALLOW_PRODUCTION_TELEGRAM_SEND=false`. |
| `apps/distribution/management/commands/seed_telegram_channel.py` | Cria/atualiza dois `SocialChannel`: `telegram_homolog` (target=`TELEGRAM_CHANNEL_ID_HOMOLOG`) e `telegram_main` (target=`TELEGRAM_CHANNEL_ID_MAIN`). Idempotente. Espelha `seed_channels.py` (que cria `whatsapp_main`+`whatsapp_principal`). |
| `apps/distribution/management/commands/pin_telegram_disclosure.py` | Envia e fixa a mensagem permanente de disclosure no canal especificado por `--channel` (default `telegram_homolog`). Idempotente — checa se já existe pin com o texto esperado. Rodar 1× por canal. |
| `apps/distribution/migrations/0004_socialchannel_add_telegram_channel.py` | Adiciona `TELEGRAM_CHANNEL = 'telegram_channel'` ao enum `ChannelType` (alter choices). Sem mudança de schema real, só metadado de choices. |

### Classes principais

- `TelegramClient` (em `telegram_client.py`)
  - `__init__(token: str | None = None, default_chat_id: str | None = None, timeout: int = 15)`
  - `send_photo(chat_id, photo_url, caption_html, inline_keyboard) -> TelegramSendResult`
  - `send_message(chat_id, text_html, inline_keyboard, disable_preview=False) -> TelegramSendResult`
  - `pin_chat_message(chat_id, message_id, disable_notification=True) -> bool`
  - `_request(method, payload)` com retry: HTTP 429 lê `parameters.retry_after`, dorme e re-tenta; HTTP 5xx backoff exponencial 1s/2s/4s/8s até 3 tentativas; lança `TelegramClientError` no fim.

- `TelegramSendResult` (frozen dataclass)
  - `success: bool`, `message_id: str`, `sent_at: datetime | None`, `error_message: str`.

- `TelegramRateLimiter` (singleton em módulo)
  - `wait_for_send(chat_id: str)` — bloqueia até janela 1s/chat + 30/s global liberar.

### Integração com agendamento

- **Opção A (recomendada para começar):** rodar `publish_telegram` num loop próprio gerenciado por `tmux` (espelhando como o `run_bot` é operado hoje), com `--once` + sleep externo. Independência total.
- **Opção B (próximo passo, opcional):** adicionar wrapper shell em `scripts/run_bot_and_telegram.sh` que chama `run_bot --once` e na sequência `publish_telegram --once`. NÃO altera `run_bot.py`.
- Opção C foi descartada (modificar `run_bot._run_cycle` para chamar Telegram) — viola a meta de não tocar no fluxo WhatsApp.

### Biblioteca escolhida

**`requests`** (já fixado em `requirements.txt` como `requests==2.32.3`).

Justificativa:
- `whatsapp_client.py` usa `urllib` direto — mesmo nível de abstração mantém o estilo do projeto.
- `python-telegram-bot==21.x` traz framework completo (Updater, Application, handlers async) — overkill para um bot que só faz `sendPhoto`/`sendMessage` e nunca recebe updates.
- `requests` é síncrono, casa com o loop síncrono do `run_bot`.
- Mantém superfície de dependência mínima — alinhado com regras `AGENTS.md` ("Use Python 3.11+ com Django 6.0.4" e ausência de framework adicional).

---

## Step 3 — Plano de implementação (ordem de execução)

### 3.1 Dependências

Nenhuma instalação nova obrigatória. `requests==2.32.3` já está em `requirements.txt`.

Verificação:

```text
$ grep -E '^requests' requirements.txt
requests==2.32.3
```

### 3.2 Variáveis de ambiente

Adicionar em `.env` (local, não versionado) e em `.env.example` (versionado, sem valores reais):

```text
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID_HOMOLOG=@descontosbothmg
TELEGRAM_CHANNEL_ID_MAIN=@descontosbotlgm
TELEGRAM_RATE_LIMIT_SECONDS=1.1
TELEGRAM_DISCLOSURE_MESSAGE=Como Associado da Amazon, ganho por compras qualificadas.
ALLOW_PRODUCTION_TELEGRAM_SEND=false
```

Em `core/settings.py`, ler com `os.environ.get` (padrão do arquivo):

```python
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHANNEL_ID_HOMOLOG = os.environ.get('TELEGRAM_CHANNEL_ID_HOMOLOG', '@descontosbothmg')
TELEGRAM_CHANNEL_ID_MAIN = os.environ.get('TELEGRAM_CHANNEL_ID_MAIN', '@descontosbotlgm')
TELEGRAM_RATE_LIMIT_SECONDS = float(os.environ.get('TELEGRAM_RATE_LIMIT_SECONDS', '1.1'))
TELEGRAM_DISCLOSURE_MESSAGE = os.environ.get(
    'TELEGRAM_DISCLOSURE_MESSAGE',
    'Como Associado da Amazon, ganho por compras qualificadas.',
)
ALLOW_PRODUCTION_TELEGRAM_SEND = os.environ.get(
    'ALLOW_PRODUCTION_TELEGRAM_SEND', 'false',
).lower() in ('1', 'true', 'yes', 'on')
```

**Importante:** `target` de cada `SocialChannel` Telegram = chat_id (`@username` ou `-100...`) lido do `.env` no `seed_telegram_channel`. O `TelegramClient` recebe o `chat_id` direto do `channel.target` — não da settings — para que cada canal aponte pro seu destino.

Logger dedicado em `LOGGING['loggers']`:

```python
'apps.distribution.telegram': {
    'handlers': ['console', 'bot_file'],
    'level': 'INFO',
    'propagate': False,
},
```

### 3.3 Arquivos a criar (caminho completo)

1. `apps/distribution/services/telegram_client.py`
2. `apps/distribution/services/telegram_rate_limiter.py`
3. `apps/distribution/services/telegram_delivery.py`
4. `apps/curation/services/telegram_message_builder.py`
5. `apps/distribution/management/commands/publish_telegram.py`
6. `apps/distribution/management/commands/seed_telegram_channel.py`
7. `apps/distribution/management/commands/pin_telegram_disclosure.py`
8. `apps/distribution/migrations/0004_socialchannel_add_telegram_channel.py` (gerada por `makemigrations`)
9. `docs/HOWTO_PUBLICAR_OFERTAS_TELEGRAM.md` — runbook operacional (criar bot via @BotFather, adicionar como admin do canal, gerar token, popular `.env`, rodar `seed_telegram_channel`, `pin_telegram_disclosure`, primeiro `--dry-run`).

### 3.4 Arquivos a modificar (com justificativa)

| Arquivo | Mudança | Justificativa |
|---|---|---|
| `apps/distribution/models.py` | Adicionar `TELEGRAM_CHANNEL = 'telegram_channel', 'Canal do Telegram'` em `SocialChannel.ChannelType`. | Único caminho compliance — sem isso o admin não consegue salvar canal Telegram. |
| `core/settings.py` | Adicionar bloco Telegram (Step 3.2) e logger. | Necessário para `BOT_TOKEN`, `CHANNEL_ID`, lock de produção. |
| `.env.example` | Adicionar bloco Telegram com valores em branco. | Documentação operacional; não versiona segredo. |
| `apps/distribution/admin.py` | Sem alteração obrigatória (admin já mostra `channel_type` via choices). Opcional: filtro por `telegram_channel`. | Cuidado: se admin tiver `list_filter` específico, validar. |
| `docs/PRD_DESCONTOS_BOT.md` § 22 (Changelog) | Adicionar entrada `### 2026-05-19 · Pós-MVP — poster Telegram (@descontosbotlgm)` descrevendo escopo, regras Amazon endereçadas (1, 2, 7), comandos de verificação. | Invariante operacional do projeto (PRD pede entrada datada por marco). |
| `docs/PRD_DESCONTOS_BOT.md` § 12 | Acrescentar subseção "Telegram" descrevendo o canal `telegram_channel`, `link_strategy=affiliate_direct` e o disclosure obrigatório. NÃO alterar a subseção WhatsApp. | Mantém o PRD como referência única. |

### 3.5 Migração de banco

Uma única migration aditiva: `apps/distribution/migrations/0004_socialchannel_add_telegram_channel.py` (gerada automaticamente após editar `ChannelType.choices`).

- Não cria tabela nova.
- Não toca em `Offer`.
- Não toca em `Delivery` (o UNIQUE existente já permite múltiplos canais).
- Reversível: a remoção do choice volta a deixar registros órfãos com valor não listado — aceitável para rollback porque o dado em si não é destruído.

Verificação esperada antes/depois:

```text
$ python3 manage.py makemigrations --dry-run
Migrations for 'distribution':
  apps/distribution/migrations/0004_socialchannel_add_telegram_channel.py
    ~ Alter field channel_type on socialchannel
```

### 3.6 Ordem de execução

1. Editar `apps/distribution/models.py` (novo choice).
2. `python3 manage.py makemigrations distribution` → confirmar o nome `0004_socialchannel_add_telegram_channel.py`.
3. `python3 manage.py migrate` (DB local).
4. Editar `core/settings.py` (vars + logger).
5. Editar `.env.example` (placeholders) e `.env` (token real + ambos channel ids, mantido fora do git).
6. Criar `apps/distribution/services/telegram_client.py`.
7. Criar `apps/distribution/services/telegram_rate_limiter.py`.
8. Criar `apps/curation/services/telegram_message_builder.py`.
9. Criar `apps/distribution/services/telegram_delivery.py`.
10. Criar `apps/distribution/management/commands/seed_telegram_channel.py`.
11. `python3 manage.py seed_telegram_channel` (cria os dois `SocialChannel`: `telegram_homolog` + `telegram_main`).
12. Criar `apps/distribution/management/commands/publish_telegram.py`.
13. Criar `apps/distribution/management/commands/pin_telegram_disclosure.py`.
14. `python3 manage.py publish_telegram --dry-run --once --channel telegram_homolog` (validação 1).
15. `python3 manage.py publish_telegram --once --limit 1 --channel telegram_homolog` (validação 2: envio real ao canal homolog — não exige `ALLOW_PRODUCTION_TELEGRAM_SEND`).
16. `python3 manage.py pin_telegram_disclosure --channel telegram_homolog` (fixa disclosure no homolog).
17. Validação opcional produção (apenas após confirmação humana visual no homolog): `ALLOW_PRODUCTION_TELEGRAM_SEND=true python3 manage.py publish_telegram --once --limit 1 --channel telegram_main` e `python3 manage.py pin_telegram_disclosure --channel telegram_main`.
18. Atualizar `docs/HOWTO_PUBLICAR_OFERTAS_TELEGRAM.md` + entrada de changelog no PRD.
19. `python3 manage.py check` + `python3 manage.py makemigrations --dry-run` (gate AGENTS.md).
20. `python3 scripts/amazon_compliance_check.py` (gate Amazon — não deve regredir).

---

## Step 4 — Formato exato da mensagem no Telegram

### Decisão de modo de envio

- **Quando `offer.image_url` for não vazio e URL HTTPS válida:** `sendPhoto` com `caption` em HTML. Caption max **1024 chars**.
- **Quando faltar imagem ou imagem for inválida:** `sendMessage` com `parse_mode=HTML` e `disable_web_page_preview=False` (Telegram gera preview a partir do `final_url`). Texto max **4096 chars**.
- **Parse mode:** **HTML** (mais simples que MarkdownV2 — só precisa escapar `<`, `>`, `&` no conteúdo dinâmico; tags estruturais são fixas).

### Estrutura da caption (≤ 1024 chars)

```text
<b>📦 {short_title}</b>

{badge}

💰 <s>De {original_price}</s>
✅ <b>Por apenas {current_price}</b>
🏷️ <b>{discount_pct}% OFF</b>

⏰ Oferta por tempo limitado!
━━━━━━━━━━━━━━━━━━━━━
<i>Como Associado da Amazon, ganho por compras qualificadas.</i>
🤖 @descontosbotlgm
```

Substituições:

- `{short_title}` = `textwrap.shorten(offer.title, width=80, placeholder='...')` + `escape_html()`.
- `{badge}` = mesma regra de intensidade do PRD §11:
  - `discount_pct >= 50` → `🚨 <b>OFERTA IMPERDÍVEL</b> 🚨`
  - `discount_pct >= 30` → `🔥 <b>ALERTA DO BOT</b> 🔥`
  - default → `⚡ <b>BOT ACHOU DESCONTO</b> ⚡`
- `{original_price}`, `{current_price}` = `R$ X.XXX,YY` (mesma função `_format_brl` — pode ser duplicada em `telegram_message_builder.py` para zero acoplamento com `message_builder.py`, ou importada como pública. Sugestão: duplicar 6 linhas para evitar dependência cruzada).
- `{discount_pct}` = inteiro arredondado.

### Botão inline "Comprar agora"

`reply_markup` JSON:

```json
{
  "inline_keyboard": [
    [
      {"text": "🛒 Comprar agora", "url": "<final_url>"}
    ]
  ]
}
```

`<final_url>` = `get_final_url(offer, channel)` reaproveitado de `apps/curation/services/message_builder.py` (a função é channel-agnostic). Para o canal Telegram `affiliate_direct`, devolve `offer.affiliate_link` (já com `tag=desconto.bot-20`).

### Disclosure de afiliado

Cumprido em duas frentes para satisfazer PRD §21.2 regra 1:

1. **Por post**: linha em itálico imediatamente acima do separador final (vide caption acima). Texto: "Como Associado da Amazon, ganho por compras qualificadas." Lido de `settings.TELEGRAM_DISCLOSURE_MESSAGE`.
2. **Pinned permanente**: comando `pin_telegram_disclosure` envia 1× a mensagem completa de disclosure (incluindo política de cookies + link `https://descontos-bot.vercel.app/disclosure`) e a fixa via `pin_chat_message(disable_notification=True)`. Verificável por `getChat`.

### Truncamento

- Calcular caption no formato acima. Se `len(caption) > 1024`:
  - Reduzir `short_title.width` em passos de 10 até caber. Mínimo 30 caracteres.
  - Se ainda passar, cair para `sendMessage` (limite 4096) em vez de `sendPhoto`.
- Texto `sendMessage` ≤ 4096 nunca deve estourar com o template atual (~ 350 chars).

### URLs e regras Amazon

- Nunca enviar URL bruta no corpo do texto — apenas no botão inline. Evita o Telegram gerar preview ambíguo que poderia conflitar com a regra 4 (sem mimetismo) e mantém o post enxuto.
- `disable_web_page_preview=True` no `sendMessage` quando usado, exceto se desejar preview de produto (decidir na revisão; default conservador = sem preview).

---

## Step 5 — Validação

### 5.1 Teste manual com 1 oferta (antes de ligar o automático)

Pré-requisitos:
- Bot criado via @BotFather; token em `.env` como `TELEGRAM_BOT_TOKEN`.
- Bot adicionado como **administrador** em **ambos** os canais (`@descontosbothmg` homolog e `@descontosbotlgm` produção) com permissões "Post Messages" e "Pin Messages".
- `ALLOW_PRODUCTION_TELEGRAM_SEND=false` mantido até o passo final de produção.

Sequência:

```bash
$ python3 manage.py check
$ python3 manage.py seed_telegram_channel
$ python3 manage.py publish_telegram --dry-run --once --channel telegram_homolog
```

Saída esperada do `--dry-run`:
- Lista 1+ oferta selecionada.
- Imprime caption HTML montada.
- Imprime URL do botão inline.
- Mensagem: "dry_run ativo: nenhuma mensagem real enviada".
- Nenhum registro novo em `Delivery`.

Em seguida, envio real ao **canal de homologação** (sem necessidade de flag de produção):

```bash
$ python3 manage.py publish_telegram --once --limit 1 --channel telegram_homolog
```

Verificações:
- Mensagem publicada no canal `@descontosbothmg` com botão "🛒 Comprar agora".
- 1 registro `Delivery` com `social_channel.code='telegram_homolog'`, `delivery_status='sent'`, `external_message_id` igual ao `message_id` do Telegram.
- Log estruturado em `logs/bot.log` com `telegram.send.ok`.

Reposts:

```bash
$ python3 manage.py publish_telegram --once --limit 1 --channel telegram_homolog
```
- Mesma oferta NÃO é reenviada para `telegram_homolog` — `deliver_offer_to_telegram` retorna `sent=False` por causa do UNIQUE.
- Mas a mesma oferta **pode** ser enviada ao `telegram_main` separadamente (UNIQUE é por canal).

Promoção a produção (apenas após inspeção visual do post no homolog):

```bash
$ ALLOW_PRODUCTION_TELEGRAM_SEND=true python3 manage.py publish_telegram --once --limit 1 --channel telegram_main
```

- Sem a env var, o comando deve recusar com mensagem `telegram_main bloqueado: defina ALLOW_PRODUCTION_TELEGRAM_SEND=true`.

### 5.2 Confirmar respeito a rate limits

- Forçar `--limit 10` numa rodada.
- Medir tempo total: deve ser `≥ 10 * TELEGRAM_RATE_LIMIT_SECONDS` (≈ 11s).
- Inserir 1 oferta com URL Amazon válida e medir log `telegram.send.ok` por offer — timestamps de `sent_at` devem estar separados por pelo menos 1s.
- Simular 429 manualmente (token inválido em ambiente de sandbox) → cliente deve respeitar `retry_after` informado pela Bot API e re-tentar.

### 5.3 Logs de envio

- Console + `logs/bot.log` recebem mensagens do logger `apps.distribution.telegram`. Padrão:
  - `telegram.send.ok offer_id=<n> message_id=<m> chat=<id> route=<affiliate_direct>`
  - `telegram.send.skipped offer_id=<n> reason=already_sent`
  - `telegram.send.silence offer_id=<n> reason=window`
  - `telegram.send.failed offer_id=<n> error=<...> retry_after=<s|->`
- Auditoria via SQLite:

```bash
$ python3 manage.py shell -c "from apps.distribution.models import Delivery; \
print(Delivery.objects.filter(social_channel__code='telegram_main') \
.values('id','delivery_status','sent_at','external_message_id','error_message')[:20])"
```

- Compliance Amazon não pode regredir:

```bash
$ python3 scripts/amazon_compliance_check.py
```
Esperado: `ALL COMPLIANCE CHECKS PASSED`.

---

## Step 6 — Riscos e mitigação

| Risco | Como detectar | Mitigação / Rollback |
|---|---|---|
| Token vazado no commit. | `git log -p .env` mostra token; alerta GitHub secret scanning. | `.env` já está no `.gitignore` (verificar antes do PR). Em caso de vazamento: `@BotFather → /revoke` imediatamente, gerar novo, atualizar `.env`, commit `.env.example` permanece sem valor. |
| Bot perde permissão de admin no canal. | `getChat` retorna sem admins; envio retorna `403`. | Logger marca `telegram.send.failed reason=403`; runbook em `HOWTO_PUBLICAR_OFERTAS_TELEGRAM.md` documenta re-adicionar bot como admin. |
| `image_url` inválida (404 / formato exótico). | `sendPhoto` devolve 400. | Cliente captura e cai para `sendMessage` sem foto na mesma chamada (1 retry). Registra `delivery_status=sent` se sucesso pela segunda via, senão `failed`. |
| Rate limit 429 mais agressivo que esperado (Telegram pode limitar a 20 msg/min em canal). | HTTP 429 com `retry_after`. | Cliente lê `retry_after`, dorme, re-tenta 1×; se 429 persistir, marca `failed` e segue. Default `TELEGRAM_RATE_LIMIT_SECONDS=1.1` (folga sobre o limite teórico de 1.0). Operador pode subir para `3.0` via `.env`. |
| Caption > 1024 mesmo após truncamento. | Validação no builder antes do envio. | Cai para `sendMessage` (até 4096) e perde foto — operador é avisado via log `telegram.fallback=text_only`. |
| Disclosure cai do topo do canal (ex.: admin desafixa). | `getChat.pinned_message` não corresponde ao texto esperado. | Re-rodar `pin_telegram_disclosure` (idempotente). Adicionar ao checklist semanal. |
| `Delivery.message` armazena versão Markdown (legado WA) e Telegram não interpreta. | Inspeção visual + comparação caption no canal. | Telegram poster grava sua caption HTML em `Delivery.message` — distinta do registro WhatsApp porque é outro `Delivery.id` (mesmo `offer` + canal diferente). |
| Loop infinito enviando posts duplicados se algum operador desabilitar a UNIQUE. | Auditoria SQL retorna >1 `Delivery` SENT por `(offer, channel)`. | UNIQUE está no schema e bloqueia. Migration de rollback NÃO remove constraint. Runbook proíbe `--fake`/`--fake-initial` sobre essa migration. |
| Canal Telegram suspenso por Telegram (spam report). | Bot API responde `400 Chat not found`. | Operador checa `t.me/descontosbotlgm`; se suspenso, contatar suporte Telegram; nenhum dado local é perdido — `Delivery` continua íntegro. |
| Confusão envio homolog vs produção. | Logs ambíguos sem `channel.code`. | Plano cria os 2 canais desde o início (`telegram_homolog` default, `telegram_main` blindado por `ALLOW_PRODUCTION_TELEGRAM_SEND`). Logger inclui `channel=<code>` em cada linha. Comando `publish_telegram` exige `--channel` explícito ou usa default homolog. |
| Quebra silenciosa do `run_bot` (loop principal) se algum import do Telegram for adicionado por engano. | `python3 manage.py check`. | Plano explicita zero edição em `run_bot.py`. Code review obrigatório no PR. Rollback = `git revert <commit>`. |

### Plano de rollback (resumo)

1. `git revert` do commit de implementação Telegram (a migration `0004_*` é segura — pode permanecer no DB sem impacto, pois só adiciona um choice; ou aplicar migration reversa antes do revert).
2. Remover linhas de env Telegram do `.env` local.
3. Desabilitar o canal via `SocialChannel.objects.filter(code='telegram_main').update(is_enabled=False)` para garantir que nenhum scheduler residual envie.
4. Comunicar no canal Telegram (manualmente) que a publicação automática está pausada para manutenção, mantendo o canal vivo.

---

## Step 7 — Sugestões fora do escopo (não implementar agora)

Apenas notas para conversa futura — **NÃO entram neste plano**:

1. Painel admin com botão "Publicar agora no Telegram" por oferta.
2. Webhook reverso para receber comandos do operador no chat privado do bot (ex.: `/republish <slug>`).
3. Métricas: contagem de cliques por botão via Telegraph/UTM e dashboard.
4. Migrar `apps.curation.services.message_builder` para uma factory que aceite `channel.channel_type` e despache para builders WA/Telegram/futuro Instagram texto — só compensa quando houver um terceiro canal de texto além de Telegram.
5. Fila Redis/Celery para rate limit cross-process. Single-process basta enquanto há 1 bot + 1 canal.
6. Comparar custo/benefício de migrar para `python-telegram-bot` se aparecer necessidade de comandos interativos.
7. Verificar/atualizar PRD §13 (silêncio 00–06 BRT) versus código (`SILENCE_END = time(8, 0)`).

---

## Gate de aceite (resumo executável)

```bash
$ python3 manage.py check
$ python3 manage.py makemigrations --dry-run
$ python3 manage.py seed_telegram_channel
$ python3 manage.py publish_telegram --dry-run --once --channel telegram_homolog
$ python3 manage.py publish_telegram --once --limit 1 --channel telegram_homolog
$ python3 manage.py pin_telegram_disclosure --channel telegram_homolog
# Promoção a produção (opcional, exige inspeção visual no homolog primeiro):
$ ALLOW_PRODUCTION_TELEGRAM_SEND=true python3 manage.py publish_telegram --once --limit 1 --channel telegram_main
$ python3 manage.py pin_telegram_disclosure --channel telegram_main
$ python3 scripts/amazon_compliance_check.py
```

Esperado em todas as etapas: status 0; canal `@descontosbothmg` recebe 1 post real com botão inline + disclosure visível (e `@descontosbotlgm` recebe o equivalente quando promovido); pinned message presente em ambos os canais; `Delivery` registrados (1 por canal); `ALL COMPLIANCE CHECKS PASSED`.
