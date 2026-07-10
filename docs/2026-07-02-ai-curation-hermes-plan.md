# Plano de Implementação — Curadoria IA Hermes para descontos.bot

Data: 2026-07-02
Projeto: `/mnt/c/Users/marce/Documents/Projetos/descontos.bot`
Arquitetura escolhida: Opção 2 — Curadoria IA assíncrona em duas etapas

## Objetivo

Substituir gradualmente a curadoria hard-coded por uma curadoria inteligente executada por um profile Hermes chamado `descontos-bot`, mantendo o fluxo atual como baseline/contexto e sem remover o código de curadoria existente.

O novo fluxo deve aumentar a conversão das ofertas enviadas, reduzir churn, balancear marketplaces e bloquear conteúdo impróprio antes do envio.

## Fluxo-alvo

```text
Scrapers → banco SQLite
  ↓
prepare_ai_curation_batch
  ↓
carrega ofertas elegíveis + baseline atual + observer + histórico
  ↓
Hermes profile descontos-bot
  ↓
JSON estruturado validado
  ↓
persistência:
  - CurationRun
  - CurationDecision
  - CuratedBatch
  - CuratedBatchItem
  - JSON local/site
  ↓
run_bot / publish_telegram consome lote ready
  ↓
Delivery WhatsApp/Telegram existente
```

## Regras obrigatórias

- Não remover a curadoria atual antes da validação em produção.
- O selector atual vira baseline/contexto, não fallback automático.
- Se Hermes/LLM falhar, o envio deve pausar e registrar/notificar o motivo.
- Toda saída do agente deve ser JSON validado por schema.
- Toda decisão deve ser auditada em banco e JSON.
- Oferta imprópria nunca pode ser enviada.
- Imagem só será analisada/processada para ofertas selecionadas para envio.
- Imagens locais devem expirar com política de 36h.
- Blacklist automática entra ativa imediatamente, mas com trilha de auditoria e rollback humano.
- Balanceamento alvo por lote:
  - Mercado Livre: 40%
  - Amazon: 30%
  - Shopee: 30%
- Persona editorial:
  - priorizar marcas conhecidas;
  - beleza, moda e tecnologia cotidiana;
  - ferramentas apenas domésticas;
  - bloquear armas, inclusive de brinquedo;
  - bloquear ferramentas pesadas, walkie-talkies, rádio comunicadores, câmeras de segurança, adulto/sexual/obsceno.

## Arquivos principais previstos

### Criar/modificar no app `curation`

- `apps/curation/models.py`
- `apps/curation/admin.py`
- `apps/curation/services/ai_schema.py`
- `apps/curation/services/baseline_snapshot.py`
- `apps/curation/services/observer_context.py`
- `apps/curation/services/batch_optimizer.py`
- `apps/curation/services/hermes_runner.py`
- `apps/curation/services/ai_prompt.py`
- `apps/curation/services/ai_curator.py`
- `apps/curation/services/image_processing.py`
- `apps/curation/services/blacklist_updates.py`
- `apps/curation/services/curated_batch_reader.py`
- `apps/curation/management/commands/prepare_ai_curation_batch.py`
- `apps/curation/management/commands/inspect_ai_curation_batch.py`
- `apps/curation/management/commands/cleanup_curation_media.py`
- `apps/curation/management/commands/rollback_curation_blacklist_term.py`

### Modificar integrações existentes

- `apps/orchestration/management/commands/run_bot.py`
- `apps/distribution/management/commands/publish_telegram.py`
- `apps/distribution/services/delivery.py`
- `apps/distribution/services/telegram_delivery.py`
- `apps/curation/services/message_builder.py`
- `apps/curation/services/telegram_message_builder.py`
- `.env.example`
- `.gitignore`

### Profile Hermes

- `/home/marce/.hermes/profiles/descontos-bot/SOUL.md`
- `/home/marce/.hermes/profiles/descontos-bot/config.yaml`

## Models propostos

### `CurationRun`

Representa uma execução de curadoria IA.

Campos sugeridos:

- `channel` — FK `SocialChannel`
- `status` — `pending`, `running`, `completed`, `failed`, `cancelled`
- `mode` — `shadow`, `dry_run`, `homolog`, `production`
- `profile_name`
- `model_provider`
- `model_name`
- `candidate_count`
- `selected_count`
- `target_distribution_json`
- `actual_distribution_json`
- `observer_context_json`
- `baseline_summary_json`
- `input_json_path`
- `output_json_path`
- `public_json_path`
- `error_message`
- `schema_version`
- timestamps

### `CurationDecision`

Uma linha por oferta analisada.

Campos sugeridos:

- `run` — FK `CurationRun`
- `offer` — FK `Offer`
- `marketplace_code`
- `baseline_score`
- `baseline_classification`
- `baseline_decision`
- `ai_score`
- `ai_classification` — `approved`, `rejected`, `improper`, `needs_image_review`
- `conversion_score`
- `relevance_score`
- `discount_quality_score`
- `audience_fit_score`
- `image_score`
- `decision_reason`
- `risk_flags_json`
- `observer_signals_json`
- `title_original`
- `title_rewritten`
- `caption_rewritten`
- `image_analysis_json`
- `blacklist_terms_json`
- `raw_ai_json`
- `is_selected_for_batch`
- timestamps

### `CuratedBatch`

Representa o lote pronto para envio.

Campos sugeridos:

- `run` — FK/OneToOne `CurationRun`
- `channel` — FK `SocialChannel`
- `status` — `draft`, `ready`, `consuming`, `sent`, `expired`, `failed`
- `batch_size`
- `target_distribution_json`
- `actual_distribution_json`
- `expires_at`
- `consumed_at`
- timestamps

### `CuratedBatchItem`

Item selecionado no lote.

Campos sugeridos:

- `batch` — FK `CuratedBatch`
- `decision` — FK `CurationDecision`
- `offer` — FK `Offer`
- `position`
- `final_title`
- `final_caption_whatsapp`
- `final_caption_telegram`
- `final_image_url`
- `local_image_path`
- `image_width`
- `image_height`
- `image_mime_type`
- `send_status` — `pending`, `sent`, `failed`, `skipped`
- `delivery` — FK opcional `Delivery`
- timestamps

### `CurationBlacklistTerm`

Audita termos inseridos automaticamente.

Campos sugeridos:

- `term`
- `normalized_term`
- `source` — `ai_image_moderation`, `ai_text_moderation`
- `offer` — FK opcional
- `decision` — FK opcional
- `run` — FK opcional
- `status` — `active`, `rolled_back`
- `added_to_setting_at`
- `rolled_back_at`
- `rollback_reason`
- timestamps

## Schema de entrada do agente

Versão: `1.0`

Exemplo resumido:

```json
{
  "schema_version": "1.0",
  "run": {
    "run_id": 123,
    "mode": "dry_run",
    "channel_code": "whatsapp_main",
    "batch_size": 20,
    "target_distribution": {
      "mercadolivre": 0.4,
      "amazon": 0.3,
      "shopee": 0.3
    }
  },
  "editorial_policy": {
    "preferred_categories": [
      "beleza_cuidados",
      "moda_feminina",
      "moda_masculina",
      "tecnologia_cotidiana",
      "casa_cozinha"
    ],
    "blocked_themes": [
      "adulto",
      "sexual",
      "obsceno",
      "armas",
      "arma_de_brinquedo",
      "ferramenta_pesada",
      "industrial",
      "walkie_talkie",
      "radio_comunicador",
      "camera_seguranca"
    ],
    "tone": "honesto, direto, persuasivo sem exagero"
  },
  "baseline_rules": {
    "min_discount_percentage": 20,
    "min_quality_score": 55,
    "priority_quality_score": 70
  },
  "observer_context": {},
  "offers": []
}
```

## Schema de saída do agente

Versão: `1.0`

Campos obrigatórios por decisão:

- `offer_id`
- `classification` — `approved`, `rejected`, `improper`
- `selected_for_batch`
- `batch_position`
- `conversion_score`
- `relevance_score`
- `discount_quality_score`
- `audience_fit_score`
- `reason`
- `rewritten_title`
- `rewritten_caption_whatsapp`
- `rewritten_caption_telegram`
- `image_required`
- `image_decision`
- `blacklist_actions`
- `risk_flags`

Regras de validação:

- `classification=improper` implica `selected_for_batch=false`.
- Se `selected_for_batch=true`, captions não podem estar vazias.
- Nenhuma oferta com `adult_content`, `weapon` ou `obscene` pode entrar no lote.
- `batch_position` deve ser único.
- Distribuição real precisa bater com os itens selecionados.
- JSON inválido ou texto livre deve falhar a execução.

## Plano por Sprints

### Sprint 0 — Preparação segura e baseline

Objetivo: garantir base segura para mudanças, sem tocar no fluxo de produção.

Tasks:

1. Verificar branch atual e working tree.
2. Criar branch de trabalho.
3. Preservar arquivos já modificados:
   - `site/offers.json`
   - `site/links.json`
   - `site/market-intel.json`, se houver.
4. Rodar checks iniciais.
5. Confirmar que o fluxo atual continua íntegro antes de qualquer alteração.

Validação:

```bash
git status
git branch
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Branch criada.
- Estado atual conhecido.
- Checks iniciais passam ou falhas preexistentes ficam documentadas.
- Nenhum comportamento funcional alterado.

Rollback:

- Voltar para branch anterior.
- Nenhum schema/código alterado ainda.

---

### Sprint 1 — Fundação de dados e auditoria

Objetivo: criar base persistente da curadoria IA sem integrar com Hermes nem envio.

Tasks:

1. Criar models de auditoria.
2. Registrar models no admin.
3. Criar migrations.
4. Criar testes básicos de criação/relacionamento.

Arquivos:

- `apps/curation/models.py`
- `apps/curation/admin.py`
- `apps/curation/tests/test_ai_curation_models.py`
- migration em `apps/curation/migrations/`

Validação:

```bash
.venv/bin/python manage.py makemigrations curation
.venv/bin/python manage.py migrate
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_ai_curation_models.py -v --tb=short
```

Critério de aceite:

- Migrations aplicam sem erro.
- Models permitem criar run, decision, batch e batch item.
- Nenhuma alteração no selector/envio atual.
- `manage.py check` passa.
- `makemigrations --dry-run` não gera migrations pendentes.

Rollback:

- Reverter migration e models na branch.
- Se migration aplicada localmente, migrar para o estado anterior.

---

### Sprint 2 — Schema JSON, baseline e contexto do observer

Objetivo: criar entrada/saída estruturada para o agente, sem chamar Hermes ainda.

Tasks:

1. Criar validação de schema JSON.
2. Criar serialização das ofertas candidatas.
3. Criar snapshot do baseline atual.
4. Criar contexto sanitizado do observer/market_intel.
5. Garantir que o JSON não exponha dados sensíveis.

Arquivos:

- `apps/curation/services/ai_schema.py`
- `apps/curation/services/baseline_snapshot.py`
- `apps/curation/services/observer_context.py`
- `apps/curation/tests/test_ai_schema.py`
- `apps/curation/tests/test_baseline_snapshot.py`
- `apps/curation/tests/test_observer_context.py`

Validação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest \
  apps/curation/tests/test_ai_schema.py \
  apps/curation/tests/test_baseline_snapshot.py \
  apps/curation/tests/test_observer_context.py \
  -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- JSON válido passa.
- JSON inválido falha.
- Oferta `improper` selecionada falha.
- Caption obrigatória para selecionadas.
- Observer context não inclui JID, sender_hash, texto bruto sensível ou URLs observadas de terceiros.
- Baseline representa corretamente `quality_score_breakdown`.

Rollback:

- Reverter serviços/testes.
- Sem impacto em produção.

---

### Sprint 3 — Batch optimizer e política editorial

Objetivo: implementar lógica determinística para lote seguro e balanceado depois da decisão IA.

Tasks:

1. Criar `batch_optimizer.py`.
2. Implementar balanceamento 40/30/30.
3. Redistribuir quando marketplace não tiver estoque bom.
4. Bloquear temas proibidos.
5. Ordenar por score IA e posição no lote.

Arquivos:

- `apps/curation/services/batch_optimizer.py`
- `apps/curation/tests/test_batch_optimizer.py`

Validação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_batch_optimizer.py -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Lote de 20 gera 8 ML, 6 Amazon e 6 Shopee quando houver estoque.
- Se faltar marketplace, redistribui sem incluir oferta ruim.
- Oferta imprópria nunca entra.
- Posições não duplicam.

---

### Sprint 4 — Runner Hermes mockado e serviço `ai_curator`

Objetivo: criar orquestrador completo da curadoria IA usando mock/fake Hermes.

Tasks:

1. Criar `hermes_runner.py`.
2. Criar `ai_prompt.py`.
3. Criar `ai_curator.py`.
4. Persistir run, decisions, batch e items.
5. Salvar JSON local de auditoria.
6. Simular falha Hermes.
7. Simular output inválido.
8. Garantir que falha não cria batch `ready`.

Arquivos:

- `apps/curation/services/hermes_runner.py`
- `apps/curation/services/ai_prompt.py`
- `apps/curation/services/ai_curator.py`
- `apps/curation/tests/test_ai_curator.py`
- `apps/curation/tests/test_hermes_runner.py`

Validação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest \
  apps/curation/tests/test_ai_curator.py \
  apps/curation/tests/test_hermes_runner.py \
  -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Mock Hermes gera batch `ready`.
- Falha Hermes gera `CurationRun.failed`.
- Output inválido falha.
- Nenhum batch `ready` é criado em falha.
- Nenhum envio real é chamado.

---

### Sprint 5 — Commands de preparação, inspeção e dry-run

Objetivo: tornar curadoria IA executável via management command, sem envio real.

Tasks:

1. Criar `prepare_ai_curation_batch`.
2. Criar `inspect_ai_curation_batch`.
3. Criar flags:
   - `--channel`
   - `--mode`
   - `--dry-run`
   - `--shadow`
   - `--candidate-limit`
   - `--skip-images`
4. Gerar JSON público sanitizado.
5. Atualizar `.gitignore`.
6. Atualizar `.env.example`.

Arquivos:

- `apps/curation/management/commands/prepare_ai_curation_batch.py`
- `apps/curation/management/commands/inspect_ai_curation_batch.py`
- `apps/curation/tests/test_prepare_ai_curation_batch_command.py`
- `.env.example`
- `.gitignore`

Validação:

```bash
.venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --mode dry_run --candidate-limit 50 --dry-run
.venv/bin/python manage.py inspect_ai_curation_batch --channel whatsapp_main
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_prepare_ai_curation_batch_command.py -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Command roda sem envio.
- Cria run/batch em modo controlado.
- `inspect` mostra decisões, distribuição e rejeições.
- JSON público não contém dados sensíveis.
- Arquivos locais de auditoria ficam fora do Git.

---

### Sprint 6 — Imagem local, multimodal e expurgo

Objetivo: adicionar processamento de imagens apenas para ofertas selecionadas.

Tasks:

1. Criar `image_processing.py`.
2. Baixar imagem das selecionadas.
3. Validar dimensões/qualidade.
4. Redimensionar quando necessário.
5. Salvar em `media/curation/...`.
6. Criar `cleanup_curation_media`.
7. Preparar campo para análise multimodal.
8. Bloquear imagem imprópria no output do agente.

Arquivos:

- `apps/curation/services/image_processing.py`
- `apps/curation/management/commands/cleanup_curation_media.py`
- `apps/curation/tests/test_image_processing.py`

Validação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_image_processing.py -v --tb=short
.venv/bin/python manage.py cleanup_curation_media --dry-run
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Imagem selecionada é baixada/processada.
- URL quebrada não derruba o run inteiro.
- Imagem ruim reprova ou marca substituição.
- Expurgo remove imagens antigas >36h.
- Nenhuma imagem de oferta `improper` vai para envio.

---

### Sprint 7 — Blacklist automática com rollback

Objetivo: permitir termos impróprios ativos com auditoria e rollback humano.

Tasks:

1. Criar `blacklist_updates.py`.
2. Adicionar termo em `Setting.blacklist_terms`.
3. Criar registro em `CurationBlacklistTerm`.
4. Evitar duplicidade.
5. Criar command rollback.
6. Garantir que rollback não remove safety hardcoded.

Arquivos:

- `apps/curation/services/blacklist_updates.py`
- `apps/curation/management/commands/rollback_curation_blacklist_term.py`
- `apps/curation/tests/test_blacklist_updates.py`

Validação:

```bash
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/test_blacklist_updates.py -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Termo novo entra em `Setting.blacklist_terms`.
- Auditoria é criada.
- Termo duplicado não duplica.
- Rollback remove termo automático.
- Rollback não remove blacklist fixa de segurança.

---


### Sprint 8 — Hermes real em dry-run/shadow mode

Objetivo: executar curadoria real com Hermes, sem envio.

Tasks:

1. Trocar mock por runner real em modo controlado.
2. Executar `prepare_ai_curation_batch` com candidate limit baixo.
3. Validar schema.
4. Validar decisões.
5. Validar captions.
6. Validar balanceamento.
7. Validar blacklist.
8. Validar imagens selecionadas.
9. Gerar relatório de comparação selector atual vs agente.

Validação:

```bash
.venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --mode shadow --candidate-limit 50
.venv/bin/python manage.py inspect_ai_curation_batch --channel whatsapp_main
.venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --mode dry_run --candidate-limit 200
.venv/bin/python manage.py inspect_ai_curation_batch --channel whatsapp_main
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/ -v --tb=short
```

Critério de aceite:

- Hermes real gera JSON válido.
- Nenhuma oferta imprópria entra no lote.
- Captions são honestas.
- Título reescrito preserva verdade factual.
- Imagem só é analisada para selecionadas.
- Lote respeita 40/30/30 quando houver estoque.
- Se falhar, run fica `failed` e não cria batch pronto.

---

### Sprint 9 — Consumo de batch curado no WhatsApp em dry-run

Objetivo: integrar `run_bot` ao lote curado, sem envio real.

Tasks:

1. Criar `curated_batch_reader.py`.
2. Alterar `run_bot.py`.
3. Adicionar flags:
   - `--ai-curation`
   - `--ai-curation-required`
   - `--prepare-ai-curation`
4. Em `--dry-run --ai-curation`, imprimir lote curado.
5. Se não houver batch ready, pausar e não usar selector antigo automaticamente.
6. Garantir modo sem IA intacto.

Arquivos:

- `apps/curation/services/curated_batch_reader.py`
- `apps/orchestration/management/commands/run_bot.py`
- `apps/orchestration/tests/test_run_bot_ai_curation.py`

Validação:

```bash
.venv/bin/python manage.py run_bot --dry-run --once --skip-scraping --channel whatsapp_main --ai-curation
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/orchestration/tests/test_run_bot_ai_curation.py -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- `run_bot --dry-run --ai-curation` consome batch pronto.
- Sem batch pronto, não envia e não cai no selector antigo.
- Modo sem `--ai-curation` permanece inalterado.
- Delivery real não é chamado em dry-run.

---

### Sprint 10 — Consumo de batch curado no Telegram em dry-run

Objetivo: integrar Telegram ao lote curado, sem envio real.

Tasks:

1. Alterar `publish_telegram.py`.
2. Permitir caption curada.
3. Permitir imagem final/local quando aplicável.
4. Validar comportamento sem batch.
5. Garantir modo antigo sem IA intacto.

Arquivos:

- `apps/distribution/management/commands/publish_telegram.py`
- `apps/curation/services/telegram_message_builder.py`
- `apps/distribution/services/telegram_delivery.py`, se necessário
- `apps/distribution/tests/test_publish_telegram_ai_curation.py`

Validação:

```bash
.venv/bin/python manage.py publish_telegram --once --channel telegram_homolog --ai-curation --dry-run
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/distribution/tests/test_publish_telegram_ai_curation.py -v --tb=short
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
```

Critério de aceite:

- Telegram dry-run usa lote curado.
- Captions respeitam limite/HTML.
- Sem batch pronto, pausa.
- Modo antigo sem IA segue funcionando.

---

### Sprint 11 — Homologação visual controlada

Objetivo: enviar lote curado para canais de homologação, com validação humana.

Pré-requisitos:

- Sprint 9 aprovada.
- Sprint 10 aprovada.
- Sprint 8 aprovada.
- Nenhuma oferta imprópria no batch.
- Captions revisadas.

Tasks:

1. Preparar batch real em modo homolog.
2. Enviar poucos itens no WhatsApp homolog (`whatsapp_main`).
3. Validar visualmente imagem, caption, link, tom, preço, desconto e marketplace.
4. Repetir no Telegram homolog (`telegram_homolog`).
5. Registrar problemas.

Comandos:

```bash
.venv/bin/python manage.py prepare_ai_curation_batch --channel whatsapp_main --mode homolog --candidate-limit 200
.venv/bin/python manage.py run_bot --once --skip-scraping --channel whatsapp_main --ai-curation
.venv/bin/python manage.py prepare_ai_curation_batch --channel telegram_homolog --mode homolog --candidate-limit 200
.venv/bin/python manage.py publish_telegram --once --channel telegram_homolog --ai-curation
```

Critério de aceite:

- Mensagens aparecem corretamente em homologação.
- Imagens renderizam.
- Links funcionam.
- Tom editorial aprovado.
- Nenhuma oferta fora da política.
- Auditoria no banco bate com envio.

---

### Sprint 12 — Produção assistida

Objetivo: rodar IA em produção de forma limitada e monitorada.

Tasks:

1. Habilitar IA para 1 ciclo controlado.
2. Preparar batch produção.
3. Revisar batch antes do envio.
4. Enviar.
5. Conferir delivery, auditoria, JSON, blacklist, imagens e distribuição.
6. Repetir por poucos ciclos antes de liberar todos.

Canais:

- WhatsApp produção: `whatsapp_principal`
- Telegram produção: `telegram_main`

Critério de aceite:

- Ciclo produção roda ponta a ponta.
- Se Hermes falhar, envio pausa.
- Nenhum fallback automático para regra antiga.
- Nenhuma oferta imprópria enviada.
- Auditoria completa.

Rollback:

- Desabilitar IA.
- Rodar fluxo antigo manualmente somente com decisão humana.
- Não deixar fallback automático.

---

### Sprint 13 — Produção plena e limpeza

Objetivo: estabilizar operação recorrente.

Tasks:

1. Definir rotina operacional.
2. Encaixar/agendar comandos no ciclo atual.
3. Garantir expurgo de mídia.
4. Revisar JSON público.
5. Documentar operação.
6. Criar checklist de incidente.

Arquivos possíveis:

- `docs/ai-curation.md`
- `docs/runbook-ai-curation.md`

Validação:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/ apps/orchestration/tests/ apps/distribution/tests/ -v --tb=short
```

Critério de aceite:

- Fluxo documentado.
- Operação reproduzível.
- Rollback documentado.
- Expurgo funcionando.
- Métricas/auditoria disponíveis.

## Sequência recomendada de execução

Primeiro lote recomendado:

```text
Sprint 0 — Preparação segura
Sprint 1 — Fundação de dados e auditoria
Sprint 2 — Schema JSON, baseline e observer context
```

Motivo:

- Não toca envio.
- Não chama Hermes real.
- Não altera produção.
- Cria a base auditável e testável.

Após esse lote, validar:

- migrations;
- models;
- schema JSON;
- baseline do selector atual;
- contexto sanitizado do observer;
- `manage.py check`;
- `makemigrations --dry-run`;
- testes focados.

Só então avançar para Sprint 3.

## Checklist global de aceite

A solução só deve ser considerada pronta quando:

1. `prepare_ai_curation_batch` cria lote `ready` com JSON válido.
2. Toda decisão do agente fica em `CurationDecision`.
3. Lote respeita ML 40%, Amazon 30%, Shopee 30%, salvo falta de estoque elegível.
4. Oferta imprópria nunca entra em `CuratedBatchItem`.
5. Termos impróprios entram na blacklist com auditoria e rollback possível.
6. Imagens das selecionadas são baixadas/processadas localmente.
7. Imagens antigas são expurgáveis.
8. `run_bot --dry-run --ai-curation` usa lote curado e não selector direto.
9. Se Hermes falhar, envio pausa e registra motivo.
10. `manage.py check`, `makemigrations --dry-run` e testes focados passam.

## Comandos finais de verificação por lote

```bash
cd /mnt/c/Users/marce/Documents/Projetos/descontos.bot

.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --dry-run

DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/curation/tests/ -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/orchestration/tests/ -v --tb=short
DJANGO_SETTINGS_MODULE=core.settings .venv/bin/python -m pytest apps/distribution/tests/ -v --tb=short
```
