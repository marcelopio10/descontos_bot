# Runbook — Curadoria IA em produção

## Rotina recorrente recomendada

### 1. Pré-check

```bash
python manage.py check
python manage.py makemigrations --dry-run
```

Confirmar serviços externos:

- WhatsApp/Evolution conectado.
- Telegram com `TELEGRAM_BOT_TOKEN` configurado.
- Canais `whatsapp_principal` e `telegram_main` habilitados.
- Flags de produção conscientemente habilitadas somente na janela de operação.

### 2. Preparar e revisar lote

```bash
python manage.py prepare_ai_curation_batch --channel whatsapp_principal --mode production --runner real --candidate-limit 200
python manage.py inspect_ai_curation_batch --channel whatsapp_principal
```

Revisar:

- imagem;
- caption;
- link final;
- preço/desconto;
- marketplace;
- motivo da IA;
- sinais de risco;
- blacklist nova.

### 3. Envio assistido

Primeiro item:

```bash
python manage.py run_bot --once --skip-scraping --channel whatsapp_principal --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --ai-curation-limit 1
```

Se visualmente aprovado, continuar com limites pequenos ou remover limite apenas após validação humana.

Telegram segue o mesmo padrão:

```bash
python manage.py prepare_ai_curation_batch --channel telegram_main --mode production --runner real --candidate-limit 200
python manage.py inspect_ai_curation_batch --channel telegram_main
python manage.py publish_telegram --once --channel telegram_main --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --limit 1
```

## Incidente / rollback

Se houver problema de conteúdo, imagem, link ou envio:

1. Parar execução recorrente.
2. Não rodar selector legado automaticamente.
3. Não reenviar o mesmo batch sem revisar itens pendentes/falhos.
4. Conferir `Delivery.error_message` e `CuratedBatchItem.send_status`.
5. Se blacklist automática adicionou termo incorreto, usar rollback específico:

```bash
python manage.py rollback_curation_blacklist_term --term "TERMO" --reason "motivo"
```

6. Rodar fluxo antigo manualmente somente com decisão humana explícita.

## Limpeza e manutenção

```bash
python manage.py cleanup_curation_media --older-than-hours 168 --dry-run
python manage.py cleanup_curation_media --older-than-hours 168
```

## Checklist de observabilidade

- `CurationRun` tem `mode`, `status`, `profile_name`, `model_provider`, `model_name`.
- `CurationDecision` existe para cada candidata.
- `CuratedBatch` reflete distribuição real.
- `CuratedBatchItem` aponta para `Delivery` quando enviado.
- `Delivery` tem `sent_at` e `external_message_id` quando sucesso.
- JSON público existe e está sanitizado.
- Nenhuma oferta imprópria foi enviada.

## Teste ponta a ponta local seguro

Para validar sem APIs externas, usar transporte mockado nos testes automatizados:

```bash
DJANGO_SETTINGS_MODULE=core.settings python -m pytest apps/distribution/tests/test_ai_curated_production_assist.py -v --tb=short
```

Para validação externa real, execute somente em janela assistida e com credenciais/canais confirmados.
