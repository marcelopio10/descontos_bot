# Curadoria IA do descontos.bot

## Objetivo

Selecionar e revisar ofertas com apoio do Hermes antes da publicação em WhatsApp e Telegram, mantendo auditoria completa e sem fallback automático para o selector legado quando a IA for obrigatória.

## Fluxo operacional

1. Preparar batch:

```bash
python manage.py prepare_ai_curation_batch --channel whatsapp_principal --mode production --runner real --candidate-limit 200
python manage.py prepare_ai_curation_batch --channel telegram_main --mode production --runner real --candidate-limit 200
```

2. Revisar batch antes de enviar:

```bash
python manage.py inspect_ai_curation_batch --channel whatsapp_principal
python manage.py inspect_ai_curation_batch --channel telegram_main
```

3. Enviar produção assistida, sempre com confirmação explícita e limite inicial:

```bash
python manage.py run_bot --once --skip-scraping --channel whatsapp_principal --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --ai-curation-limit 1
python manage.py publish_telegram --once --channel telegram_main --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --limit 1
```

4. Conferir auditoria:

- `CurationRun.status = completed`
- `CuratedBatch.status` permanece `ready` quando só parte do lote foi enviada; vira `sent` quando todos os itens forem enviados.
- `CuratedBatchItem.send_status` reflete `pending`, `sent`, `failed` ou `skipped`.
- `CuratedBatchItem.delivery` aponta para a `Delivery` criada.
- `Delivery.delivery_status`, `external_message_id`, `sent_at` e `error_message` mostram o resultado externo.

## Guardas de segurança

- Produção IA exige confirmação textual:
  - `--confirm-ai-production CONFIRM_AI_PRODUCTION`
- WhatsApp produção também continua respeitando `ALLOW_PRODUCTION_WHATSAPP_SEND`.
- Telegram produção continua respeitando `ALLOW_PRODUCTION_TELEGRAM_SEND`.
- Use `--ai-curation-required` em produção para impedir fallback automático para o selector legado.
- Use limite pequeno (`--ai-curation-limit 1` / `--limit 1`) na fase assistida.

## Limpeza de mídia

Imagens antigas processadas pela curadoria devem ser expurgadas periodicamente:

```bash
python manage.py cleanup_curation_media --older-than-hours 168 --dry-run
python manage.py cleanup_curation_media --older-than-hours 168
```

## JSON público

O JSON público da curadoria deve permanecer sanitizado:

- sem URL afiliada bruta;
- sem URL de produto bruta;
- sem payload bruto de IA;
- sem tokens ou dados sensíveis;
- somente campos necessários para revisão/observabilidade.

## Critérios finais de aceite

- Batch pronto e revisado antes do envio.
- Nenhuma oferta imprópria em `CuratedBatchItem`.
- Hermes falhou ou não gerou batch? O envio pausa quando `--ai-curation-required` está ativo.
- Envio assistido cria `Delivery` e amarra auditoria item/batch.
- Rollback documentado e testado.
