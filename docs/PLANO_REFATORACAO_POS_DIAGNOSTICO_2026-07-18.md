# Plano de Refatoração descontos.bot — Sprints com Verificação Manual

> Derivado do laudo `Projetos/descontos.bot/diagnostico_descontos_bot_v1.md` (v1.2). Este plano transforma o backlog em 4 ondas em **8 sprints executáveis**, cada um com **verificação manual ao final** (checkpoint go/no-go).
>
> **Decisão explícita do dono:** **não há testes automatizados neste plano.** A verificação de cada sprint é **comportamental/manual** — rodar comandos reais, observar saída, consultar o banco/painel, forçar falhas e observar recuperação. Onde o laudo pediria teste automatizado, este plano usa verificação por observação.

**Data:** 2026-07-18 · **Base de código:** `/mnt/c/Users/marce/Documents/Projetos/descontos.bot` · **Branch de trabalho sugerida:** `refactor/pos-diagnostico`

## Como usar este plano
- Execute **uma sprint por vez**, em ordem. Só avance quando a **Verificação da Sprint** passar (todos os itens ✅).
- Cada tarefa lista **arquivos** (criar/modificar) e **passos** concretos. Faça **commits frequentes** (um por tarefa concluída).
- Se um passo falhar na verificação, **não avance** — corrija dentro da própria sprint.
- Trechos de código são **ilustrativos** (mostram a forma da mudança), não cópia-cola cega: adapte à assinatura real do arquivo ao editar.

## Restrições de negócio (do laudo — sobrepõem qualquer passo em conflito)
- **RESTR-01** — WhatsApp já roda via **Evolution API** (Baileys é fallback). Mudanças de transporte miram Evolution; falhas de lógica do loop (throttle/retry) são independentes do transporte.
- **RESTR-02** — API de afiliado de **ML e Amazon indisponível** para a conta → **manter scraping, blindado**. Só Shopee tem API.
- **RESTR-03** — Rastreamento de clique próprio (interceptação) **falhou e é desencorajado** → atribuição por **SubID nativo (Shopee)** + **correlação temporal (ML/Amazon)**.
- **RESTR-04** — Só **Shopee** tem relatório exportável → ingestão automática só da Shopee; ML/Amazon manuais.
- **RESTR-05** — **Proibido publicar preço histórico** → histórico de preço é **uso interno** de curadoria; nunca aparece na mensagem.

## Mapa Onda → Sprint
| Onda (laudo) | Sprints |
|---|---|
| Onda 0 — Estabilizar e medir | Sprint 0 (preparação), Sprint 1 (reativar canais), Sprint 2 (medir + infra) |
| Onda 1 — Desacoplar e rastrear | Sprint 3 (entrega resiliente + desacoplar), Sprint 4 (atribuição possível) |
| Onda 2 — Inteligência | Sprint 5 (curadoria confiável), Sprint 6 (radar + observer + scraping blindado) |
| Onda 3 — Crescimento | Sprint 7 (Instagram + growth) |

---

## Sprint 0 — Preparação e salvaguardas
**Objetivo:** montar um ambiente seguro para refatorar sem interromper a operação nem arriscar o banco. Duração estimada: 0,5 dia.

### Tarefa 0.1 — Branch de trabalho e baseline
**Arquivos:** nenhum (git).
- Passo 1: criar a branch a partir do estado atual: `git checkout -b refactor/pos-diagnostico`.
- Passo 2: registrar o commit-base no topo desta doc (preencher): `git rev-parse HEAD`.
- Passo 3: rodar `python manage.py check` e anotar a saída (baseline "sem issues" esperado).

### Tarefa 0.2 — Backup do banco e rotina de backup diário
**Arquivos:** Criar `scripts/backup_db.sh`.
- Passo 1: fazer cópia imediata: `cp data/descontos_bot.db data/descontos_bot.$(date +%Y%m%d).bak.db` (com o serviço parado, ou usando `.backup` do SQLite se disponível).
- Passo 2: criar `scripts/backup_db.sh` que copia `data/descontos_bot.db` para `data/backups/` com carimbo de data e mantém os últimos 7.
- Passo 3: (opcional) criar `scripts/backup-db.timer`/`.service` systemd diário, espelhando `scripts/fetch-clicks.timer`.

### Tarefa 0.3 — Verificar integridade do banco (achado 3.2-D do laudo)
**Arquivos:** nenhum.
- Passo 1: rodar `python -c "import sqlite3; c=sqlite3.connect('data/descontos_bot.db'); print(c.execute('PRAGMA quick_check').fetchone())"`.
- Passo 2: se a saída for `('ok',)`, seguir. Se acusar corrupção, executar `VACUUM INTO` para um arquivo novo e substituir só após confirmar `quick_check = ok` na cópia.

### ✅ Verificação da Sprint 0 (go/no-go)
- [ ] `git branch --show-current` retorna `refactor/pos-diagnostico`.
- [ ] Existe backup do `.db` em `data/backups/` e `scripts/backup_db.sh` roda sem erro.
- [ ] `PRAGMA quick_check` retorna `ok` (ou o banco foi recuperado por `VACUUM INTO` e agora retorna `ok`).
- [ ] `python manage.py check` sem issues.
**Só avançar se todos ✅.**

---

## Sprint 1 — Reativar canais e cadência (Onda 0 · parte 1)
**Objetivo:** parar a sangria de volume. Religar o Telegram, colocar throttle no WhatsApp e evitar que uma desconexão zere o lote. Duração: 2–3 dias.
**Restrições aplicáveis:** RESTR-01.

### Tarefa 1.1 — Diagnosticar e religar o Telegram principal (achado C2)
**Arquivos:**
- Investigar: `apps/distribution/management/commands/publish_telegram.py`, `apps/distribution/services/telegram_client.py`, `core/settings.py` (token `TELEGRAM_BOT_TOKEN`, `ALLOW_PRODUCTION_TELEGRAM_SEND`).
- Modificar (se necessário): `scripts/` (criar unidade systemd para publicação Telegram se hoje é manual).
- Passos:
  1. Rodar um dry-run: `DJANGO_SETTINGS_MODULE=core.settings python manage.py publish_telegram --dry-run --once --channel telegram_main`. Observar erro real (token expirado? canal? exceção?).
  2. Corrigir a causa observada (renovar token no `.env`, corrigir `SocialChannel`, etc.). **Não** inventar causa — agir sobre a saída do passo 1.
  3. Confirmar a última entrega no banco: `python -c "import sqlite3;c=sqlite3.connect('data/descontos_bot.db');print(c.execute(\"select max(sent_at) from distribution_delivery where social_channel_id=4\").fetchone())"` antes e depois.
  4. Enviar 1 item real controlado: `... publish_telegram --once --channel telegram_main --confirm-ai-production CONFIRM_AI_PRODUCTION --limit 1` (com `ALLOW_PRODUCTION_TELEGRAM_SEND=true`).

### Tarefa 1.2 — Throttle de envio no WhatsApp (achado D / H3)
**Arquivos:**
- Reusar: `apps/distribution/services/telegram_rate_limiter.py` (já existe, referência de design).
- Criar: `apps/distribution/services/whatsapp_rate_limiter.py` (limiter por número: intervalo mínimo entre mensagens + janela).
- Modificar: `apps/distribution/services/delivery.py` (aplicar o limiter dentro de `deliver_offer_to_channel`/`deliver_curated_item_to_whatsapp`, antes de cada `send_message`).
- Passos:
  1. Definir parâmetros configuráveis via `panel.Setting` ou env: `WA_MIN_INTERVAL_SECONDS` (ex.: 8–15s) e janela por hora.
  2. Implementar o limiter (sleep até liberar o slot), espelhando a lógica do `telegram_rate_limiter.py`.
  3. Chamá-lo no caminho de envio WhatsApp em `delivery.py`.
  4. Ilustrativo:
     ```python
     # apps/distribution/services/whatsapp_rate_limiter.py (exemplo)
     def wait_for_slot(min_interval_seconds: float) -> None:
         elapsed = time.monotonic() - _last_sent_monotonic()
         if elapsed < min_interval_seconds:
             time.sleep(min_interval_seconds - elapsed)
         _mark_sent()
     ```

### Tarefa 1.3 — Não queimar o lote inteiro em desconexão (achado C3, mitigação mínima)
**Arquivos:** Modificar `apps/orchestration/management/commands/run_bot.py` (loop de envio `~274-303` e ciclo curado `~365-397`) e/ou `apps/distribution/services/delivery.py:59-69`.
- Passos:
  1. Antes do loop de envio, checar a sessão **uma vez**; se estiver caída, **fail-fast**: não iterar marcando N ofertas como FAILED. Registrar motivo e sair do ciclo cedo (as ofertas continuam elegíveis no próximo ciclo).
  2. Dentro do loop, se um envio falhar por indisponibilidade transitória, **parar o lote** (a sessão caiu) em vez de marcar todas as seguintes como FAILED.
  3. Ilustrativo: introduzir uma exceção `SessaoIndisponivelError` que interrompe o loop, distinta de erro de uma oferta específica.
  4. Nota RESTR-01: isso vale para o transporte Evolution — é lógica do loop Python.

### Tarefa 1.4 — Cadência mínima de envio por canal
**Arquivos:** Modificar `apps/orchestration/services/scheduler.py` e/ou `panel.Setting`.
- Passos:
  1. Garantir um teto/piso de itens por ciclo por canal (evitar rajada e evitar zero).
  2. Documentar no `docs/RUNBOOK_PRODUCAO.md` a cadência-alvo diária por canal.

### ✅ Verificação da Sprint 1 (go/no-go)
- [ ] **Telegram religado:** `select max(sent_at) from distribution_delivery where social_channel_id=4` mostra data de **hoje**; 1 item real chegou no canal `@descontosbotlgm`.
- [ ] **Throttle ativo:** rodar um ciclo real pequeno e medir o intervalo entre `sent_at` consecutivos no WhatsApp — deve respeitar `WA_MIN_INTERVAL_SECONDS`. Query: `select sent_at from distribution_delivery where social_channel_id=2 order by sent_at desc limit 5`.
- [ ] **Sem lote queimado:** derrubar propositalmente a sessão WhatsApp (parar o Evolution/adapter) e rodar 1 ciclo — confirmar que **NÃO** aparecem dezenas de `failed` contíguos; o ciclo sai cedo com um único motivo registrado. Query: `select delivery_status,count(*) from distribution_delivery where date(created_at)=date('now') group by 1`.
- [ ] `rate-overlimit` **não** reaparece após religar (monitorar por 1 dia): `select count(*) from distribution_delivery where error_message like 'rate-overlimit%' and created_at > <início da sprint>`.
- [ ] Commit por tarefa feito.

---

## Sprint 2 — Medir e endurecer a base (Onda 0 · parte 2)
**Objetivo:** passar a enxergar (KPI de envios, detecção de scraper quebrado, ingestão de relatórios) e endurecer infra/segurança. Duração: 3–4 dias.
**Restrições aplicáveis:** RESTR-02, RESTR-04.

### Tarefa 2.1 — KPI de envios/dia por canal + painel mínimo (achado C1 / 8.4)
**Arquivos:**
- Criar: `apps/analytics/services/operational_metrics.py` (agregações de `Delivery`, `ScrapingRun`, `CurationRun`).
- Criar comando: `apps/analytics/management/commands/painel_operacional.py` (imprime o painel diário no terminal e/ou grava JSON).
- Passos:
  1. Implementar agregações: envios/dia por canal, ofertas coletadas/válidas, runs FAILED (scraping/curadoria), última coleta do observer.
  2. Comando imprime tabela diária e grava `site/painel-operacional.json` (protegido, se publicado).
  3. Verificação por observação (não teste automatizado): rodar o comando e conferir os números contra queries diretas no banco.

### Tarefa 2.2 — Detector de scraper quebrado + alertas (achados A / 8.5)
**Arquivos:** Modificar `apps/scraping/services/runner.py` (guarda `~63-66`) e `scrapers/base.py` (detecção de bloqueio).
- Passos:
  1. Estender o guarda de "0 ofertas válidas" para **todos os marketplaces** (hoje só Amazon) e adicionar `log.error` (hoje só grava em `ScrapingRun.error_message`).
  2. Marcar `ScrapingRun=FAILED` quando ciclo inteiro retornar 0 cards + latência anômala.
  3. Disparar **alerta via Telegram do operador** (bot de handoff já existe) em: scraper 0-cards, observer > 24h sem coleta, envios/dia abaixo de limiar, run de curadoria FAILED em sequência, canal sem entrega em 24h.
  4. Criar `apps/analytics/services/alertas.py` centralizando o disparo.

### Tarefa 2.3 — Supervisão do observer (achado B / 7.2)
**Arquivos:** Criar `scripts/market-intel.service` e `scripts/market-intel.timer` (systemd), espelhando `scripts/fetch-clicks.timer`.
- Passos:
  1. Timer diário (ex.: 22h BRT) executando `scripts/market_intel_daily.sh`.
  2. Adicionar healthcheck próprio do observer: se `market_intel_observedwhatsappmessage` não tem mensagem nova há > 24h, alerta (usa `alertas.py` da 2.2).
  3. RESTR-01: a instabilidade de sessão é do transporte Evolution/externo; aqui garantimos **supervisão do pipeline de coleta**, que é o gargalo controlável.

### Tarefa 2.4 — Segurança: SECRET_KEY e DEBUG (achado G)
**Arquivos:** Modificar `core/settings.py:33,36`; atualizar `.env` e `.env.example`.
- Passos:
  1. Mover `SECRET_KEY` para `os.environ`; gerar chave nova (rotacionar a antiga).
  2. `DEBUG` lido de env, default `False`.
  3. Ajustar `ALLOWED_HOSTS` conforme ambiente.

### Tarefa 2.5 — Rotação de logs + `busy_timeout` do SQLite (achados MÉDIOS)
**Arquivos:** Modificar `core/settings.py` (logging `~290-304`, `DATABASES` `~230-247`).
- Passos:
  1. Trocar `FileHandler` por `RotatingFileHandler` (limite de tamanho + backups) para `logs/bot.log` e afins.
  2. Adicionar `OPTIONS={'timeout': 30}` ao `DATABASES['default']` e/ou `PRAGMA busy_timeout` no signal `configure_sqlite_connection`.

### Tarefa 2.6 — Ingestão dos relatórios de afiliado (Item 0 do backlog; RESTR-04)
**Arquivos:**
- Usar: `apps/analytics/management/commands/ingest_affiliate_amazon.py`, `ingest_affiliate_mercadolivre.py` (entrada manual).
- Criar: `apps/analytics/management/commands/ingest_affiliate_shopee.py` (Shopee é exportável → automatizável, lê SubIds).
- Passos:
  1. Ingerir os dados de `Relatórios Market Places.md` (ML/Amazon manual; Shopee via comando novo).
  2. Rodar `publish_affiliate_summary` e conferir o dashboard.
  3. Documentar o processo manual de ML/Amazon em `docs/AFFILIATE_REPORTS_INGESTION.md` (já existe — atualizar).

### ✅ Verificação da Sprint 2 (go/no-go)
- [ ] **Painel:** `python manage.py painel_operacional` imprime envios/dia por canal e os números batem com queries diretas no banco.
- [ ] **Detector de scraper:** forçar 0-card (ex.: apontar a URL para um host inválido em ambiente de teste) e confirmar `ScrapingRun=FAILED` + alerta recebido no Telegram do operador.
- [ ] **Observer supervisionado:** `systemctl --user list-timers` mostra `market-intel.timer`; simular > 24h sem coleta e receber alerta.
- [ ] **Segurança:** `grep SECRET_KEY core/settings.py` **não** mostra chave literal; `DEBUG` vem do ambiente; chave antiga rotacionada.
- [ ] **Logs/DB:** `logs/bot.log` rotaciona (arquivo novo ao atingir o limite); `PRAGMA busy_timeout` retorna valor > 0.
- [ ] **Relatórios:** dashboard/`affiliate-summary.json` mostra comissão por marketplace do período; Shopee ingerida pelo comando novo.
- [ ] Commits feitos.

---

## Sprint 3 — Entrega resiliente e desacoplamento (Onda 1 · parte 1)
**Objetivo:** transformar a entrega em fila com re-tentativa (dead-letter) e começar a desacoplar o `run_bot`. Duração: 4–5 dias.
**Restrições aplicáveis:** RESTR-01.

### Tarefa 3.1 — Fila de envio com estados + retry/backoff/dead-letter (achado C3 completo)
**Arquivos:**
- Modificar: `apps/distribution/models.py` (usar/estender `Delivery` com estados de fila: `pendente`, `enviando`, `enviado`, `falha_transitoria`, `dead_letter`) ou criar `fila_envio`.
- Criar: `apps/distribution/services/fila_envio.py` (consumidor que lê pendentes, tenta enviar com backoff, move para dead-letter após N tentativas).
- Criar comando: `apps/distribution/management/commands/processar_fila_envio.py`.
- Passos:
  1. Ao curar/selecionar, **enfileirar** itens (status `pendente`) em vez de enviar direto no `run_bot`.
  2. `processar_fila_envio` consome a fila respeitando o throttle (Sprint 1) e faz backoff exponencial em falha transitória.
  3. Após N tentativas, move para `dead_letter` com motivo (não reenvia em loop).
  4. Idempotência: manter a reserva `_reserve_delivery_for_send` (`delivery.py:198-257`); um item `enviado` nunca reenvia.

### Tarefa 3.2 — Idempotência do Telegram (achado MÉDIO)
**Arquivos:** Modificar `apps/distribution/services/telegram_delivery.py:48-60`.
- Passos:
  1. Usar `_reserve_delivery_for_send`/`select_for_update` no caminho Telegram, como no WhatsApp (evita duplicata sob concorrência).

### Tarefa 3.3 — Extrair responsabilidades do `_run_cycle` atrás de feature flag (achado P5)
**Arquivos:** Modificar `apps/orchestration/management/commands/run_bot.py` (`_run_cycle:204-303`); criar consumidores em `apps/orchestration/services/` que leem tabelas de estado.
- Passos:
  1. Introduzir flag (`panel.Setting` `USA_FILA_DESACOPLADA`, default off).
  2. Com a flag ligada: `run_bot` só coleta e enfileira; a curadoria e o envio rodam por consumidores próprios (`processar_fila_envio` da 3.1) — desacoplamento por tabela de estados (ADR-001 do laudo).
  3. Rollback = desligar a flag (volta ao caminho atual).

### ✅ Verificação da Sprint 3 (go/no-go)
- [ ] **Retry real:** derrubar a sessão no meio de um lote e observar que os itens não-enviados ficam `pendente`/`falha_transitoria` e são **reprocessados** no próximo ciclo, **sem duplicar** os já enviados. Query de duplicidade: `select offer_id, social_channel_id, count(*) from distribution_delivery where delivery_status='sent' group by 1,2 having count(*)>1` deve retornar **0 linhas**.
- [ ] **Dead-letter:** forçar N falhas de um item e confirmar que ele vai para `dead_letter` com motivo, sem loop infinito.
- [ ] **Telegram idempotente:** rodar dois `publish_telegram` concorrentes no mesmo lote e confirmar 1 mensagem por item (sem duplicata).
- [ ] **Flag de desacoplamento:** com `USA_FILA_DESACOPLADA=on`, `run_bot` só enfileira; com off, comportamento antigo intacto (rollback comprovado).
- [ ] **Não-regressão:** envios/dia (painel da Sprint 2) não caíram durante a sprint.
- [ ] Commits feitos.

---

## Sprint 4 — Atribuição possível (Onda 1 · parte 2)
**Objetivo:** medir o que é medível — canal via SubID na Shopee e correlação temporal para ML/Amazon. Duração: 2–3 dias.
**Restrições aplicáveis:** RESTR-03, RESTR-04.

### Tarefa 4.1 — SubID Shopee → canal na conversão (achado C5, parte viável)
**Arquivos:** Modificar `apps/analytics/services/affiliate_summary.py`, `apps/marketplaces/services/shopee_link_generator.py:36-44` (subIds), `ingest_affiliate_shopee.py` (Sprint 2.6).
- Passos:
  1. Garantir que o SubID gravado no link Shopee codifica o **canal** (`subId2`/campanha) de forma parseável.
  2. Na ingestão Shopee, ler o SubID do relatório e preencher `AffiliateConversion.social_channel` (hoje sempre `None`).
  3. `affiliate_summary` deixa de colapsar Shopee em "organico" quando há SubID.

### Tarefa 4.2 — Correlação temporal envios × comissão (ML/Amazon)
**Arquivos:** Modificar `apps/analytics/services/operational_metrics.py` (Sprint 2.1) e o painel.
- Passos:
  1. Cruzar, por marketplace e por semana, **envios/canal** (que o sistema controla) com **comissão do marketplace** (dos relatórios).
  2. Deixar explícito no painel que ML/Amazon são **correlação**, não atribuição exata (RESTR-03).

### Tarefa 4.3 — Expectativa realista do click tracking Amazon (RESTR-03)
**Arquivos:** documentar em `docs/LINK_POLICY.md`.
- Passos:
  1. Registrar que o `ClickEvent`/`/api/click` Amazon é best-effort e **não** será expandido para outros marketplaces (interceptação desencorajada). Sem novo desenvolvimento aqui — apenas manter e documentar.

### ✅ Verificação da Sprint 4 (go/no-go)
- [ ] **Shopee atribuída:** após ingerir um relatório Shopee, `select social_channel_id, count(*) from analytics_affiliateconversion where source='shopee' group by 1` mostra canal preenchido (não só `NULL`).
- [ ] **Correlação no painel:** o painel mostra, por marketplace/semana, envios/canal ao lado da comissão, com rótulo "correlação (ML/Amazon)".
- [ ] **Documentação:** `LINK_POLICY.md` registra a decisão RESTR-03.
- [ ] Commits feitos.

---

## Sprint 5 — Curadoria confiável (Onda 2 · parte 1)
**Objetivo:** eliminar ofertas quase idênticas, desconto falso (uso interno) e texto de IA repetitivo/quebrado. Duração: 4–5 dias.
**Restrições aplicáveis:** RESTR-05.

### Tarefa 5.1 — Deduplicação por produto canônico (achado P8)
**Arquivos:** Modificar `apps/offers/services/normalizer.py` (hash `~105-107`) e `apps/curation/services/selector.py` (dedupe `~154-259`).
- Passos:
  1. Introduzir `produto_canonico_id` na `Offer` (marca+modelo+identificador quando houver: ASIN/GTIN/itemId), separado do `offer_hash` (que é de URL).
  2. Na seleção, evitar publicar duas ofertas do **mesmo produto canônico** que diferem só por vendedor/centavos.
  3. Migration para o novo campo + backfill dos existentes onde possível.

### Tarefa 5.2 — Histórico de preço INTERNO + anti-desconto-falso (achado F / H5; RESTR-05)
**Arquivos:** Criar modelo `apps/offers/models.py` (`historico_preco`); modificar `apps/curation/services/quality_score.py` e `normalizer.py`.
- Passos:
  1. Persistir série de preço por oferta (a cada coleta).
  2. No score, penalizar desconto cujo "De R$" diverge do mínimo histórico observado internamente.
  3. **RESTR-05:** o histórico é **exclusivamente interno**. Garantir que **nenhum** valor histórico entre em `message_builder.py`/`telegram_message_builder.py`. Único carimbo permitido: "preço coletado em DD/MM".

### Tarefa 5.3 — Humanizar fallback, badge e sanitizar saída da IA (achado P9)
**Arquivos:** Modificar `apps/curation/services/message_builder.py` (fallback `~120-130`, badge `146`), `telegram_message_builder.py:158`, `hermes_runner.py` (parsing/sanitização).
- Passos:
  1. Substituir o fallback determinístico ("boa opção para...", "boa oportunidade para quem já estava procurando") por **variações contextuais** (ou por deixar vazio o highlight quando não houver caption boa, sem frase-clichê).
  2. Rotacionar/variar o badge fixo "⚡ BOT ACHOU DESCONTO ⚡".
  3. Adicionar sanitização anti-vazamento de raciocínio nas strings da IA (remover blocos de "pensamento"/`<think>`/meta) antes de renderizar.

### Tarefa 5.4 — Estabilizar tamanho do lote e timeout da curadoria IA (achado E)
**Arquivos:** Modificar `apps/orchestration/management/commands/run_bot.py:52-54` (constantes `AI_CURATION_*`), `apps/curation/management/commands/prepare_ai_curation_batch.py`, `apps/curation/services/hermes_runner.py`.
- Passos:
  1. Medir itens publicados/dia pós-curadoria vs. baseline legado (usar painel da Sprint 2). O laudo observou lotes pequenos (candidate 12 → selected 4) e 31 runs FAILED por "timeout de 600s".
  2. Ajustar o **tamanho-alvo do lote** por canal e a tolerância a timeout (`AI_CURATION_RUNNER_TIMEOUT`) para reduzir falhas sem inflar latência.
  3. Confirmar que a taxa de `CurationRun` FAILED cai abaixo de 10%.

### ✅ Verificação da Sprint 5 (go/no-go)
- [ ] **Dedupe:** preparar um lote (dry-run) com duas ofertas do mesmo produto/vendedores diferentes e confirmar que **só uma** é selecionada. `... run_bot --dry-run --once --skip-scraping` e inspecionar o lote.
- [ ] **Lote/timeout:** `select status,count(*) from curation_curationrun where created_at > <início da sprint> group by 1` mostra taxa de FAILED < 10%; itens/dia estáveis na meta definida.
- [ ] **Desconto falso penalizado (interno):** inserir manualmente uma oferta com "De R$" inflado e confirmar que o score cai — **sem** que nenhum dado histórico apareça na mensagem renderizada (revisar a saída do dry-run).
- [ ] **Compliance RESTR-05:** `grep -ri "menor preço\|era R\$\|preço histórico\|histórico de preço" apps/curation/services/*message*` **não** encontra publicação de histórico.
- [ ] **Texto IA:** rodar 10 dry-runs e revisar as captions — sem repetição das frases-clichê, sem badge idêntico em todas, sem vazamento de raciocínio.
- [ ] Commits feitos.

---

## Sprint 6 — Radar de mercado, loop do observer e coleta blindada (Onda 2 · parte 2)
**Objetivo:** curadoria guiada por venda real; observer retroalimentando o score; scraping ML/Amazon blindado. Duração: 5–6 dias.
**Restrições aplicáveis:** RESTR-02.

### Tarefa 6.1 — Módulo `radar_mercado` (achado P7)
**Arquivos:** Criar `apps/marketplaces/services/radar_mercado.py`; usar `apps/marketplaces/services/shopee_collectors.py:16-32,46-48` (`sortType`/`listType`/`sales`).
- Passos:
  1. Coletar ranking de vendas da Shopee via API oficial (variando `sortType`/`listType`), 1×/dia.
  2. Gerar `escore_venda` por categoria/produto.
  3. Alimentar o `quality_score` e o payload do Hermes com o sinal.

### Tarefa 6.2 — Ligar o observer à curadoria (achado P3 — hoje código morto)
**Arquivos:** Modificar `apps/curation/management/commands/prepare_ai_curation_batch.py:61-65` (dict estático) e `apps/curation/services/quality_score.py`; usar `apps/curation/services/observer_context.py:14` (`build_observer_context`, hoje só chamado por teste).
- Passos:
  1. Substituir o `observer_context` estático pela chamada real a `build_observer_context` (dados agregados e sanitizados).
  2. Somar bônus ao score para categorias/marketplaces recorrentes nos grupos observados.
  3. Garantir sanitização (sem dados brutos de terceiros — LGPD, doc 24).

### Tarefa 6.3 — Blindar scraping ML e Amazon (achado C; RESTR-02)
**Arquivos:** Modificar `scrapers/mercado_livre.py:100,395`, `scrapers/amazon.py` (backoff `131`), criar monitor de cookie.
- Passos:
  1. Trocar `requests` puro do ML por **curl-cffi** (TLS impersonation, como na Amazon).
  2. Criar **monitor de expiração** de `ML_COOKIE`/`ML_CSRF_TOKEN` com alerta **antes** de vencer (usa `alertas.py`).
  3. Backoff exponencial com jitter na Amazon (hoje fixo `[0,2,4,8]`).
  4. **Não** migrar para API (indisponível — RESTR-02).

### Tarefa 6.4 — Reponderar distribuição/curadoria por receita real (item 20 do backlog)
**Arquivos:** Modificar `apps/curation/management/commands/prepare_ai_curation_batch.py` (distribuição-alvo hoje 40% ML / 30% Amazon / 30% Shopee), `apps/curation/services/ai_prompt.py`.
- Passos:
  1. Base (laudo 4.5): **Mercado Livre = 92% da comissão**; Amazon converte melhor (20,7%) com poucos cliques. A distribuição-alvo atual sub-representa o que paga.
  2. Ajustar a distribuição-alvo à luz da receita real (aumentar peso de ML; testar mais exposição Amazon como experimento controlado).
  3. Tratar como **experimento**: medir comissão por marketplace antes/depois (painel Sprint 4), não como mudança permanente cega.

### ✅ Verificação da Sprint 6 (go/no-go)
- [ ] **Reponderação:** a distribuição-alvo reflete a decisão baseada em receita; o experimento de exposição Amazon tem baseline registrado no painel para comparação depois.
- [ ] **Radar:** `radar_mercado` produz um ranking de vendas Shopee do dia; conferir que categorias do topo ganham bônus no score (inspecionar um lote dry-run com/sem radar).
- [ ] **Observer ligado:** confirmar (por log/inspeção do payload da curadoria) que `build_observer_context` é chamado em produção e altera o `observer_context_json` do `CurationRun` (não mais o dict estático). Query: `select observer_context_json from curation_curationrun order by created_at desc limit 1`.
- [ ] **ML blindado:** rodar coleta ML e confirmar uso de curl-cffi; simular cookie perto de expirar e receber alerta antes de quebrar.
- [ ] **Amazon backoff:** inspecionar log de um retry e confirmar intervalos exponenciais com jitter.
- [ ] Commits feitos.

---

## Sprint 7 — Crescimento: Instagram e retenção (Onda 3)
**Objetivo:** religar a produção de conteúdo e estabelecer cadência e medição de crescimento. Duração: 4–5 dias.
**Restrições aplicáveis:** RESTR-03, RESTR-05.

### Tarefa 7.1 — Religar a geração de conteúdo Instagram (achado C4)
**Arquivos:** Modificar `apps/orchestration/management/commands/run_bot.py:485-493,567-575` (remover o `return` inalcançável e reativar de forma controlada); revisar `apps/social_posts/services/post_generator.py`, `apps/social_posts/management/commands/generate_instagram_*.py:14-19`.
- Passos:
  1. Remover os `return` que desligam a geração; reativar sob **política de cadência** (não gerar em rajada).
  2. Corrigir a contradição do `PLANO_AUTOMACAO_INSTAGRAM.md` (que diz "ativo").
  3. Manter publicação por **handoff via Telegram** (Link Sticker de story continua manual — API não cria).

### Tarefa 7.2 — Calendário editorial e cadência (achado P6)
**Arquivos:** Criar `apps/social_posts/services/politica_cadencia.py`; documentar em `docs/ROTINA_EDITORIAL_INSTAGRAM.md`.
- Passos:
  1. Implementar limite diário (ex.: 3 stories + 1 feed/carrossel) e espaçamento.
  2. Usar os tops do `radar_mercado` (Sprint 6) como pauta ("Top 5 mais vendidos hoje").
  3. CTA "link na bio → canais gratuitos" (sem promessa financeira — compliance).

### Tarefa 7.3 — Medir crescimento e retenção (achado H9)
**Arquivos:** Criar modelo `apps/analytics/models.py` (`metrica_canal_diaria`: data, canal, membros/seguidores, posts, cliques estimados).
- Passos:
  1. Registrar contagem de membros por canal ao longo do tempo (entrada manual periódica é aceitável — LGPD: só agregados, RESTR/doc 24).
  2. Painel mostra a curva de membros por canal.

### ✅ Verificação da Sprint 7 (go/no-go)
- [ ] **Geração religada:** rodar 1 ciclo e confirmar que **novos** `InstagramPost` são criados (`select max(created_at) from social_posts_instagrampost` = hoje) e entram na fila de handoff.
- [ ] **Cadência:** confirmar que a política respeita o limite diário (não gera em rajada) — inspecionar contagem gerada por dia.
- [ ] **Handoff:** um story chega ao Telegram do operador com imagem + caption + URL do sticker.
- [ ] **Membros:** `metrica_canal_diaria` recebe pelo menos 1 registro por canal e o painel plota a curva.
- [ ] Commits feitos.

---

## Verificação global (após a Sprint 7)
- [ ] **Volume recuperado:** envios/dia por canal estáveis ou crescentes vs. início do plano (painel Sprint 2).
- [ ] **Canais no ar:** WhatsApp, Telegram e Instagram todos com atividade nos últimos 7 dias.
- [ ] **Medição:** comissão por marketplace visível no dashboard; Shopee atribuída por canal; correlação ML/Amazon no painel.
- [ ] **Resiliência:** derrubar sessão não zera lote; scraper quebrado gera alerta; observer supervisionado.
- [ ] **Compliance:** nenhum preço histórico publicado; sem interceptação de clique nova; disclosure/tag Amazon intactos (`python scripts/amazon_compliance_check.py` → `ALL COMPLIANCE CHECKS PASSED`).
- [ ] **Operação nunca parou** durante a refatoração (feature flags permitiram rollback por etapa).

## Notas de execução
- **Sem testes automatizados** por decisão do dono: toda verificação é por comando + observação. Se no futuro quiser cobertura automatizada, ela entra como um plano separado.
- **Feature flags** (`panel.Setting`) protegem cada mudança arriscada; rollback = desligar a flag.
- **Compliance é invariante:** rodar `scripts/amazon_compliance_check.py` antes de cada merge que toque em link/mensagem.
- Referência de origem: `diagnostico_descontos_bot_v1.md` (v1.2), Seções 3 (achados), 5–10 (arquitetura/estratégia) e 11 (backlog ICE).
