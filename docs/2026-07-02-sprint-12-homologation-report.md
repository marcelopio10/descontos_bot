# Sprint 12 — Homologação visual controlada

> Nota: este relatório preserva a numeração original do plano antes da remoção da sprint de criação do profile Hermes. No plano atualizado, esta etapa corresponde à Sprint 11 — Homologação visual controlada.

Status: implementação e simulação ponta a ponta concluídas; envio visual externo bloqueado por configuração local.

## Implementado

- WhatsApp `run_bot --ai-curation` agora envia lote curado em modo não dry-run para canal homologado.
- Telegram `publish_telegram --ai-curation` agora envia lote curado em modo não dry-run para canal homologado.
- Cada item enviado atualiza:
  - `Delivery`
  - `CuratedBatchItem.send_status`
  - `CuratedBatchItem.delivery`
  - `CuratedBatch.status` para `sent` quando todos os itens são enviados.
- Captions e imagens finais do batch são usadas no envio:
  - WhatsApp: `final_caption_whatsapp` e `local_image_path/final_image_url/offer.image_url`.
  - Telegram: payload curado já escapado/truncado da Sprint 11.

## Validação executada

- Testes automatizados com transporte mockado confirmaram envio, mensagem, imagem, entrega e auditoria.
- Simulação local com banco migrado e batch `homolog` preparado executou:
  - `run_bot --once --skip-scraping --channel whatsapp_main --ai-curation`
  - `publish_telegram --once --channel telegram_homolog --ai-curation`
- Resultado da simulação:
  - WhatsApp: `Enviadas 3/3 com curadoria IA.`
  - Telegram: `Enviadas 3/3 com curadoria IA.`
  - Batches: `sent`
  - Itens: `sent`
  - Deliveries: `sent`

## Bloqueios para validação visual externa nesta máquina

- `TELEGRAM_BOT_TOKEN_configured = False`, então o envio real para Telegram Bot API não pode ser validado visualmente daqui.
- `wa_service` em `127.0.0.1:8787` recusou conexão.
- Evolution adapter em `127.0.0.1:8788` respondeu conectado, mas o banco local usado no worktree contém target seedado (`descontos.bot homolog`) para teste, não um canal/grupo real confirmado para homologação visual.

## Próximo passo manual para validação visual

Com credenciais/canais reais de homologação configurados, rodar:

```bash
python manage.py prepare_ai_curation_batch --channel whatsapp_main --mode homolog --candidate-limit 200
python manage.py run_bot --once --skip-scraping --channel whatsapp_main --ai-curation
python manage.py prepare_ai_curation_batch --channel telegram_homolog --mode homolog --candidate-limit 200
python manage.py publish_telegram --once --channel telegram_homolog --ai-curation
```

Validar visualmente imagem, caption, link, tom, preço, desconto e marketplace nos canais de homologação.
