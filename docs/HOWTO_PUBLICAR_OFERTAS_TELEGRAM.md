# HOWTO — Publicar Ofertas no Telegram

Runbook operacional para o poster Telegram (@descontosbotlgm em produção,
@descontosbothmg em homologação).

> **Origem do plano:** `docs/superpowers/plans/2026-05-19-telegram-poster.md`
> **Princípio:** isolado do poster WhatsApp. Não altera `run_bot`.

---

## 1. Pré-requisitos

- Bot Telegram criado via [@BotFather](https://t.me/BotFather) (comando `/newbot`).
- Token salvo em `.env` como `TELEGRAM_BOT_TOKEN=...` (nunca commitar).
- Bot adicionado como **administrador** em **ambos** os canais
  (`@descontosbothmg` e `@descontosbotlgm`) com permissões:
  - "Post Messages" (obrigatório)
  - "Pin Messages" (obrigatório para o disclosure)
- `python3 manage.py migrate` aplicado (inclui migration `0004_alter_socialchannel_channel_type`).

## 2. Variáveis de ambiente

Adicionar ao `.env` (já documentado em `.env.example`):

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHANNEL_ID_HOMOLOG=@descontosbothmg
TELEGRAM_CHANNEL_ID_MAIN=@descontosbotlgm
TELEGRAM_RATE_LIMIT_SECONDS=1.1
TELEGRAM_DISCLOSURE_MESSAGE=Como Associado da Amazon, ganho por compras qualificadas.
ALLOW_PRODUCTION_TELEGRAM_SEND=false
```

Manter `ALLOW_PRODUCTION_TELEGRAM_SEND=false` até validar visualmente o homolog.

## 3. Bootstrap inicial (uma vez por ambiente)

```bash
python3 manage.py migrate
python3 manage.py seed_telegram_channel
python3 manage.py pin_telegram_disclosure --channel telegram_homolog
```

`seed_telegram_channel` cria os dois `SocialChannel` (idempotente).
`pin_telegram_disclosure` envia + fixa a mensagem permanente de disclosure
(também idempotente — re-rodar não duplica).

## 4. Ciclo de publicação

### 4.1 Dry-run (sempre antes do envio real)

```bash
python3 manage.py publish_telegram --dry-run --once --channel telegram_homolog
```

Esperado: lista das ofertas selecionadas + caption HTML + URL do botão.
Não grava nada em `Delivery`.

### 4.2 Envio real ao canal de homologação

```bash
python3 manage.py publish_telegram --once --limit 1 --channel telegram_homolog
```

Não precisa de `ALLOW_PRODUCTION_TELEGRAM_SEND` (esse flag só protege
`telegram_main`).

Verificar:
- Post no canal `@descontosbothmg` com botão "🛒 Comprar agora".
- `Delivery` correspondente:
  ```bash
  python3 manage.py shell -c "from apps.distribution.models import Delivery; \
  print(list(Delivery.objects.filter(social_channel__code='telegram_homolog') \
  .values('id','delivery_status','external_message_id','sent_at')[:5]))"
  ```
- Log em `logs/bot.log` com `telegram.send.ok`.

### 4.3 Promoção para produção

Apenas depois de inspeção visual OK no homolog:

```bash
python3 manage.py pin_telegram_disclosure --channel telegram_main
ALLOW_PRODUCTION_TELEGRAM_SEND=true python3 manage.py publish_telegram \
  --once --limit 1 --channel telegram_main
```

Sem o flag, o comando recusa com mensagem explícita.

### 4.4 Loop contínuo (operação normal)

O comando suporta `--once` apenas. Para loop em produção, usar `tmux` ou
`nohup` com sleep externo, exatamente como `run_bot`:

```bash
tmux new -s telegram_main
ALLOW_PRODUCTION_TELEGRAM_SEND=true bash -c '
while true; do
  python3 manage.py publish_telegram --once --channel telegram_main
  sleep $((90 * 60 + RANDOM % (90 * 60)))
done'
```

Sair do tmux: `Ctrl-b d`. Reattach: `tmux a -t telegram_main`.

## 5. Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `TELEGRAM_BOT_TOKEN não configurado.` | `.env` vazio ou não carregado. | Conferir `.env` na raiz; reiniciar shell. |
| `Bot API recusou: chat not found` | Bot não foi adicionado ao canal, ou chat_id errado. | Verificar admin + valor de `TELEGRAM_CHANNEL_ID_*`. |
| `403 Forbidden` em envios | Bot perdeu admin. | Re-promover no Telegram → "Administrators". |
| `429` repetido | Rate limit do Telegram excedido. | Subir `TELEGRAM_RATE_LIMIT_SECONDS=3.0` no `.env`. |
| Post sem imagem | `image_url` 404 → fallback automático para `sendMessage`. | Log `telegram.fallback=text_only` confirma. |
| Pinned message sumiu | Admin desafixou. | `python3 manage.py pin_telegram_disclosure --channel <code> --force`. |
| `telegram_main bloqueado: ...` | Flag de produção desligado. | `ALLOW_PRODUCTION_TELEGRAM_SEND=true` no `.env` ou inline. |

## 6. Vazamento de token (incident response)

1. `@BotFather` → `/mybots` → escolher bot → "API Token" → "Revoke current token".
2. Token novo no `.env`. **Nunca** commitar.
3. Auditar `git log -p -- .env` para confirmar que nada escapou.
4. Se token chegou ao GitHub: rotate + abrir issue interno + notificar.

## 7. Rollback

```bash
SocialChannel.objects.filter(code='telegram_main').update(is_enabled=False)
```

Mantém o canal vivo; só pausa envios automáticos. Comunicar manualmente
no canal que está em manutenção.

Para reverter código completo: `git revert <commit>` da branch
`feat/telegram-poster`. A migration `0004` é segura — pode ficar aplicada
sem efeito quando o choice volta a não existir.

## 8. Compliance Amazon (não regredir)

Cada publicação no Telegram deve manter:
- `final_url` com `tag=desconto.bot-20` (lido de `offer.affiliate_link`).
- Disclosure por post (linha em itálico no rodapé).
- Pinned message com política completa.

Gate antes de commit/PR:

```bash
python3 scripts/amazon_compliance_check.py
```

Esperado: `ALL COMPLIANCE CHECKS PASSED`.
