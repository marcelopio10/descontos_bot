# Handoff manual de stories Instagram via Telegram

Este doc descreve a rotina pra entregar stories prontos do `descontos.bot` no Telegram do PO, que então publica manualmente no app do Instagram (onde o link sticker funciona nativamente).

Fluxo resumido:

```
gerador (manage.py generate_instagram_story)
   ↓
InstagramPost(status=ready) criado
   ↓
deliver_post_to_handoff envia PNG + caption + URL do sticker no DM Telegram
   ↓
status passa pra awaiting_post
   ↓
PO posta manualmente no IG (cola URL no link sticker)
   ↓
PO clica "✅ Marcar como postado" no Telegram
   ↓
listener daemon detecta callback e marca status=posted
```

## 1. Criar o bot dedicado

Abra `@BotFather` no Telegram:

```
/newbot
Nome: descontos.bot handoff
Username: descontos_bot_handoff_bot   (precisa terminar em "bot")
```

O BotFather devolve um token tipo `123456:ABC...`. Guarda esse token.

Recomendações:

- Use bot **dedicado** pro handoff. Não reuse o token do Hermes — Telegram só permite um consumidor (long-poll ou webhook) por token, e usar o mesmo bot quebra o Hermes.
- Em `@BotFather → /mybots → seu bot → Bot Settings → Allow Groups?` deixe **desabilitado**. Esse bot é só pra DM.

## 2. Configurar `.env`

Adicione no `.env` (na raiz do projeto):

```env
INSTAGRAM_HANDOFF_BOT_TOKEN=<token recebido do BotFather>
INSTAGRAM_HANDOFF_CHAT_ID=<seu chat_id pessoal — próximo passo>
INSTAGRAM_HANDOFF_QUIET_HOURS_BRT=22:00-08:00
INSTAGRAM_TIMEZONE=America/Sao_Paulo
```

Sem `INSTAGRAM_HANDOFF_BOT_TOKEN` ou `INSTAGRAM_HANDOFF_CHAT_ID`, o handoff é desativado silenciosamente — geração de posts continua funcionando normalmente.

## 3. Descobrir seu `chat_id` pessoal

Com o token preenchido no `.env`:

```bash
python3 manage.py discover_handoff_chat_id --seconds 60
```

Enquanto o comando estiver rodando, abra o bot no Telegram (busque pelo username) e mande `/start` (ou qualquer mensagem). O terminal imprime algo como:

```
chat_id=123456789 username=@seu_user first_name=Seu Nome type=private
```

Copie o `chat_id` numérico pro `.env`:

```env
INSTAGRAM_HANDOFF_CHAT_ID=123456789
```

## 4. Iniciar o listener (daemon)

O listener long-poll capta seus cliques no botão "✅ Marcar como postado" e atualiza o banco.

**Foreground (uso normal de desenvolvimento):**

```bash
python3 manage.py telegram_handoff_listener
```

**Background (rotina diária):**

```bash
nohup python3 manage.py telegram_handoff_listener \
    >> logs/handoff_listener.log 2>&1 &
```

**Debug rápido (1 ciclo):**

```bash
python3 manage.py telegram_handoff_listener --once
```

Sobe lockfile em `/tmp/instagram_handoff_listener.lock` pra impedir 2 daemons concorrentes (Telegram aceita apenas 1 long-poll por bot token).

Se o lockfile ficar órfão (laptop travou e não limpou), apague manualmente:

```bash
rm /tmp/instagram_handoff_listener.lock
```

## 5. Rotina do dia a dia

1. Gerar story:
   ```bash
   python3 manage.py generate_instagram_story --top 1
   ```
   Resultado: `InstagramPost` criado, asset PNG renderizado, e mensagem chega no seu Telegram com:
   - Documento PNG (não comprimido).
   - Texto com a caption pronta + URL do sticker em bloco destacado.
   - Botão inline "✅ Marcar como postado".

2. Abrir Telegram (desktop ou celular). Baixar PNG, copiar caption, copiar URL.

3. Abrir Instagram → criar story → escolher imagem da galeria → adicionar **link sticker** → colar URL → posicionar → publicar.

4. Voltar pro Telegram e clicar **"✅ Marcar como postado"**. Toast confirma e o botão some.

5. Sistema: `InstagramPost.status = posted`, `posted_at = now()`.

## 6. Fallback quando o daemon estiver offline

Se o laptop estiver desligado ou o daemon parou, o clique no Telegram não atualiza o DB. Resolva por uma destas vias:

- **Subir o daemon** e clicar de novo no botão (idempotente).
- **Django Admin**: `descontos.bot/admin/social_posts/instagrampost/` → selecionar post `awaiting_post` → ação **"Marcar como postado manualmente (com edição do botão Telegram)"**. Isso atualiza o DB **e** edita o botão na mensagem do Telegram pra mostrar "✅ Postado".

## 7. Re-enviar pacote

Se a mensagem foi apagada ou nunca chegou:

Django Admin → selecionar post → ação **"Re-enviar pacote Telegram (handoff)"**. Limpa o `telegram_handoff_message_id` e dispara `deliver_post_to_handoff` de novo.

## 8. Quiet hours

`INSTAGRAM_HANDOFF_QUIET_HOURS_BRT=22:00-08:00` (default): mensagens geradas dentro dessa janela vão com `disable_notification=true` — chegam no Telegram, mas sem som/vibração. Posts gerados de madrugada ficam disponíveis pra você ver de manhã sem te acordar.

Pra desativar: deixe a env vazia (`INSTAGRAM_HANDOFF_QUIET_HOURS_BRT=`).

Pra usar outra janela: `INSTAGRAM_HANDOFF_QUIET_HOURS_BRT=23:00-07:00`.

## 9. Fluxos paralelos não impactados

- WhatsApp (`wa_service`) e Telegram channel (`@descontosbotlgm`) continuam usando o `TELEGRAM_BOT_TOKEN` original. Sem conflito.
- O Composio publisher (`publish_instagram_post`, action "Publicar via Composio") continua disponível como fallback técnico no Admin — útil pra testes ou se você quiser publicar via API alguma exceção. Não é o fluxo principal.

## 10. Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `discover_handoff_chat_id` não imprime nada | Não mandou mensagem pro bot certo | Confira username do bot no @BotFather e tente de novo |
| Mensagem chega mas botão não funciona | Daemon parado | `ps aux \| grep telegram_handoff_listener`; subir de novo |
| `Sem permissão` no clique | `INSTAGRAM_HANDOFF_CHAT_ID` no `.env` ≠ seu chat_id | Re-rodar `discover_handoff_chat_id` e atualizar `.env` |
| Listener falha com `lock já em execução` | Daemon zumbi ou crashou sem limpar | `rm /tmp/instagram_handoff_listener.lock` |
| PNG chega borrado | (não deveria — vai como document) | Confirma que está usando `send_document` no service (não `send_photo`) |
| `Arquivo não encontrado` no log | Asset PNG sumiu do disco | Re-gerar com `generate_instagram_story` |
