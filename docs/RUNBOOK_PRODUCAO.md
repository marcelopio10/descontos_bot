# Runbook — Ativação do canal de produção WhatsApp

Comandos exatos para liberar o canal `whatsapp_principal` (grupo `descontos.bot`)
após o sign-off da homologação. Execute em ordem; cada passo tem critério próprio.

## Pré-requisitos

- [ ] Compliance Amazon validado em homologação (rodada `run_bot --once` no `whatsapp_main`).
- [ ] Canal público de WhatsApp cadastrado no portal Amazon Associates.
- [ ] Grupo fechado removido das fontes do portal Amazon Associates.
- [ ] 5+ ofertas publicadas no Instagram oficial.
- [ ] `scripts/amazon_compliance_check.py` retorna `ALL COMPLIANCE CHECKS PASSED`.
- [ ] `wa_service` conectado e pareado com a conta oficial (`curl http://127.0.0.1:8787/status`).

## Estado inicial esperado

- `whatsapp_principal` existe, enabled, target `descontos.bot`, `link_strategy=bridge_only` (provisionado por `seed_channels`).
- `.env` com `ALLOW_PRODUCTION_WHATSAPP_SEND=false` — guard ativo, qualquer envio para `descontos.bot` é bloqueado em `apps/orchestration/management/commands/run_bot.py::_validate_channel_for_real_delivery`.

## Passo 1 — Confirmar canais provisionados

```bash
python3 manage.py seed_channels
```

Saída esperada:

```
Canal WhatsApp homologação atualizado com destino "descontos.bot - Homologação".
Canal WhatsApp principal atualizado com destino "descontos.bot".
```

## Passo 2 — Liberar guard de produção

Editar `.env`:

```
ALLOW_PRODUCTION_WHATSAPP_SEND=true
```

Confirmar (settings precisa ler do ambiente — usar shell que carregou o `.env`):

```bash
python3 -c "from django.conf import settings; import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings'); django.setup(); print(settings.ALLOW_PRODUCTION_WHATSAPP_SEND)"
```

Deve retornar `True`. Se voltar `False`, o `.env` não está sendo carregado pelo shell — exportar manualmente as variáveis antes.

## Passo 3 — Smoke test dry-run no canal de produção

```bash
python3 manage.py run_bot --dry-run --once --skip-scraping --channel whatsapp_principal
```

Verificar no stdout:

- `Canal: WhatsApp principal (whatsapp_principal)`.
- Links Amazon começam por `https://descontos-bot.vercel.app/r?slug=...`.
- Links Mercado Livre começam por `https://meli.la/...`.
- `whatsapp_link_resolved` no log com `route=bridge_redirect` (Amazon) ou `affiliate_direct_non_public` (ML).
- `dry_run ativo: nenhuma mensagem real foi enviada e nenhuma entrega foi gravada.`

Se algo divergir, parar — não avançar para envio real.

## Passo 4 — Primeiro ciclo real (smoke test)

```bash
python3 manage.py run_bot --once --channel whatsapp_principal
```

Acompanhar:

- `Publicação automática finalizada` com `offers_count` recente, `committed=True`, `pushed=True`.
- Cada `Entrega: sent` (id, externo preenchido).
- `Publicação offers.json: cutoff=... janela_horas=36 elegiveis=N` no log.

Se aparecer `rate-overlimit` em cascata (vários failed seguidos), interromper o ciclo (Ctrl+C) e aguardar 30-60 min antes da próxima execução. Rate-limit acumulado do WhatsApp é resolvido pelo intervalo natural entre ciclos (`cycle_min_minutes=90`, `cycle_max_minutes=180`).

## Passo 5 — Validação no grupo de produção

No grupo `descontos.bot`:

- [ ] Mensagens chegaram com template oficial.
- [ ] Links Amazon `/r?slug=...` mostram disclosure e redirecionam para Amazon mantendo `tag=desconto.bot-20`.
- [ ] Links Mercado Livre abrem direto na loja.
- [ ] Sem duplicatas, sem texto proibido.

## Rollback rápido

Se algo der errado durante ou depois do Passo 4:

1. Editar `.env`: `ALLOW_PRODUCTION_WHATSAPP_SEND=false`.
2. Parar qualquer scheduler ativo (`Ctrl+C`).
3. Confirmar com `python3 manage.py run_bot --once --channel whatsapp_principal` — deve falhar com `Envio real para o grupo de produção "descontos.bot" está bloqueado`.

Ofertas já enviadas permanecem em `Delivery sent` e não voltam em ciclos futuros — não há ação adicional necessária.

## Próximos ciclos (operação contínua)

Após o smoke test passar:

```bash
python3 manage.py run_bot --channel whatsapp_principal
```

Cadência controlada por `Setting`:

- `cycle_min_minutes` (padrão 90)
- `cycle_max_minutes` (padrão 180)

A janela 00:00–06:00 BRT continua bloqueando distribuição (silêncio configurado em `apps/distribution/services/execution_window.py`).

---

# Runbook — Ativação do login do site privado (Sprint 7A)

Protege `/dashboard`, `/inteligencia` e os JSONs sensíveis (`affiliate-summary.json`, `market-intel.json`) no deploy Vercel.

## Pré-requisitos

- [ ] Acesso ao painel Vercel do projeto (Root Directory = `site/`).
- [ ] `npm install` rodado em `site/` (instala `@vercel/edge`); no deploy a Vercel instala sozinha.

## Passo 1 — Gerar segredos

```bash
openssl rand -hex 32          # use como SITE_AUTH_SECRET
SITE_AUTH_SECRET='<secret-gerado>' node site/scripts/hash-password.mjs '<senha-do-operador>'
```

Guarde o secret e a senha no cofre (1Password/Bitwarden). Nunca no vault nem no Git.

## Passo 2 — Configurar Environment Variables no Vercel

No projeto Vercel (Production e Preview):

```
SITE_AUTH_USER=operador
SITE_AUTH_PASSWORD_HASH=<saída do hash-password.mjs>
SITE_AUTH_SECRET=<secret gerado>
SITE_AUTH_SESSION_TTL_SECONDS=28800
```

## Passo 3 — Validar em `vercel dev` antes do deploy

```bash
cd site
npm install
vercel dev
```

- `/` , `/oferta?slug=...`, `/links` abrem sem login.
- `/dashboard` sem sessão redireciona para `/login?next=/dashboard`.
- Login válido abre `/dashboard`; `/inteligencia` abre com a mesma sessão.
- `GET /affiliate-summary.json` e `/market-intel.json` sem sessão retornam 401.
- "Sair" bloqueia `/dashboard` novamente.
- `next=https://site-malicioso.com` não redireciona para fora.

## Passo 4 — Deploy e verificação em produção

Após push/deploy, repetir as checagens do Passo 3 na URL pública e confirmar no DevTools que o cookie `descontos_bot_session` está `HttpOnly` e `Secure`.

## Rollback

1. Renomear/remover `site/middleware.js` e reverter os rewrites de auth no `site/vercel.json`.
2. Redeploy. As páginas voltam ao comportamento público anterior.
3. (Opcional) Remover as variáveis `SITE_AUTH_*` do Vercel.

---

# Runbook — Automação do canal Telegram principal (`publish-telegram.timer`)

O comando `manage.py publish_telegram` nunca foi automatizado — dependia de execução
manual, e ficou sem rodar a partir de 2026-07-03 até a criação deste timer (Sprint 1,
Tarefa 1.1 do plano de refatoração pós-diagnóstico). A partir de agora, a publicação no
canal Telegram principal (`SocialChannel` code=`telegram_main`, target `@descontosbotlgm`)
é disparada automaticamente por `scripts/publish-telegram.service` +
`scripts/publish-telegram.timer`, seguindo o mesmo padrão do `fetch-clicks.timer`.

## Cadência-alvo

- Timer dispara a cada 30 minutos (`OnUnitActiveSec=30min`), com `OnBootSec=5min` e
  `Persistent=true` (recupera o ciclo perdido se a máquina estava desligada no horário).
- Isso equivale a até ~48 ciclos/dia; o volume real de mensagens publicadas por dia
  depende do número de ofertas elegíveis retornadas pela curadoria IA em cada ciclo
  (`--ai-curation`, padrão do comando) — o timer só garante que o ciclo rode, não força
  volume fixo de posts.
- Cada execução é `Type=oneshot` com `--once`: um ciclo por disparo, sem loop contínuo.

## Instalação (systemd --user)

```bash
systemctl --user daemon-reload
systemctl --user enable --now publish-telegram.timer
```

Verificar:

```bash
systemctl --user list-timers publish-telegram.timer
journalctl --user -u publish-telegram.service -n 50
tail -f ~/descontos.bot/logs/publish-telegram.log
```

## Guard de produção

O `ExecStart` já inclui `--confirm-ai-production CONFIRM_AI_PRODUCTION`, exigido pelo
próprio comando para publicar de fato no canal (confirmar com
`python3 manage.py publish_telegram --help`). Validar sintaxe sem enviar nada:

```bash
python3 manage.py publish_telegram --dry-run --once --channel telegram_main --confirm-ai-production CONFIRM_AI_PRODUCTION
```

## Rollback rápido

```bash
systemctl --user disable --now publish-telegram.timer
```

Isso interrompe os disparos futuros sem afetar entregas já registradas.
