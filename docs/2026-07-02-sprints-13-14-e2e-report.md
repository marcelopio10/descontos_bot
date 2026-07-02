# Sprints 13–14 — Relatório de teste ponta a ponta

## Escopo

Executadas produção assistida e estabilização operacional da curadoria IA.

## Valores locais clonados da main

A worktree combinada foi criada em:

`/home/marce/.config/superpowers/worktrees/descontos.bot/ai-curation-sprint-13-14`

Foi tentada a cópia local de `.env`, `.env.local`, `db.sqlite3` e `data/db.sqlite3` a partir de:

`/mnt/c/Users/marce/Documents/Projetos/descontos.bot-evolution-migration`

Resultado: a main não tinha esses arquivos locais disponíveis. Para concluir o E2E, os canais e ofertas mínimos foram seedados no banco local migrado da própria worktree.

## E2E executado

1. Migrações locais aplicadas.
2. Canais seedados:
   - `whatsapp_principal` → `descontos.bot`
   - `telegram_main` → `-100999`
3. Ofertas elegíveis seedadas para Amazon, Mercado Livre e Shopee.
4. Preparação de batches em modo `production`:
   - `prepare_ai_curation_batch --channel whatsapp_principal --mode production --candidate-limit 3 --skip-images`
   - `prepare_ai_curation_batch --channel telegram_main --mode production --candidate-limit 3 --skip-images`
5. Envio assistido com transporte mockado, confirmação explícita e limite 1:
   - WhatsApp: `run_bot --once --skip-scraping --channel whatsapp_principal --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --ai-curation-limit 1`
   - Telegram: `publish_telegram --once --channel telegram_main --ai-curation-required --confirm-ai-production CONFIRM_AI_PRODUCTION --limit 1`
6. Auditoria conferida.
7. Limpeza de mídia validada em dry-run:
   - `cleanup_curation_media --older-than-hours 168 --dry-run`

## Resultado

- WhatsApp: `Enviadas 1/1 com curadoria IA.`
- Telegram: `Enviadas 1/1 com curadoria IA.`
- `CurationRun.mode = production` para ambos.
- `CuratedBatch.status = ready` porque o limite 1 deixou dois itens pendentes por canal.
- `CuratedBatchItem.send_status = ['sent', 'pending', 'pending']` por canal.
- `Delivery.delivery_status = sent` para o item enviado.
- External IDs mockados:
  - WhatsApp: `wa-e2e-1`
  - Telegram: `tg-e2e-1`
- Limpeza: `cleanup_curation_media dry_run scanned=0 would_delete=0`

## Observação importante

O E2E não chamou APIs externas reais. Isso foi intencional para concluir a validação de produção assistida com segurança dentro da worktree. Para envio externo real, usar o runbook e confirmar credenciais/canais antes da janela assistida.
