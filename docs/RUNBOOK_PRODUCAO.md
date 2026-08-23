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

---

# Runbook — Throttle e cadência de envio no WhatsApp (Sprint 1, Tarefas 1.2 e 1.4)

Duas proteções complementares no caminho de envio WhatsApp
(`apps/distribution/services/delivery.py`,
`apps/orchestration/management/commands/run_bot.py`), ambas configuráveis via
`panel.Setting` (chave-valor, sem precisar de deploy):

1. **Throttle entre mensagens** (`apps/distribution/services/whatsapp_rate_limiter.py`):
   intervalo mínimo entre envios consecutivos ao mesmo destino, para evitar
   `rate-overlimit` no provedor (achado D/H3).
2. **Cadência por ciclo** (`apps/orchestration/services/scheduler.py::get_channel_cadence_config`):
   teto/piso de itens enviados por ciclo por canal, para evitar rajada e evitar
   ciclo "zero" quando há itens elegíveis (achado C3/H3).

## Configuração (Settings)

| Setting | Padrão | Efeito |
|---|---|---|
| `wa_min_interval_seconds` | `10` (segundos) | Intervalo mínimo entre um `send_message` e o próximo, por destino. |
| `wa_max_sends_per_hour` | `0` (desativado) | Teto opcional de envios/hora por destino; `0` = sem teto. |
| `channel_items_min_per_cycle` | `1` | Piso informativo: loga aviso se o lote elegível ficar abaixo disso (não força itens inexistentes). |
| `channel_items_max_per_cycle` | `25` | Teto: corta o lote do ciclo nesse tamanho antes de iniciar o envio. Calibrado contra o volume real observado (lotes de 15-20 itens são comuns em dias de pico, maior lote observado: 20) — um teto menor cortaria volume normal, não só rajada patológica. |

Ajustar via painel/shell, ex.:

```bash
python3 manage.py shell -c "from apps.panel.models import Setting; Setting.objects.update_or_create(key='wa_min_interval_seconds', defaults={'value': '12'})"
```

## Cadência-alvo diária (canal WhatsApp)

Com os padrões acima e o intervalo entre ciclos do scheduler
(`cycle_min_minutes=90`, `cycle_max_minutes=180`, média ~135min):

- ~8 a 11 ciclos por dia (`1440min / ~135min`).
- Até 25 itens por ciclo (teto padrão) → **teto diário de referência: ~200-275 itens/dia**
  no canal WhatsApp principal, sem estourar o intervalo mínimo de 10s entre envios
  dentro do mesmo ciclo (25 itens × 10s ≈ 250s, desprezível frente aos 90-180min entre ciclos).
- O teto de 25 foi calibrado contra o volume real dos últimos 7 dias (medido diretamente
  no banco, agrupando `sent_at` por janelas de 5min): lotes de 15-20 itens são comuns em
  dias de pico, maior lote observado = 20. Volume diário observado no período: 20-95
  itens/dia. Um teto de 8 (valor inicial da implementação) cortaria cerca de metade dos
  lotes normais — corrigido antes de ir para produção.
- Volume real fica abaixo do teto na prática: depende de quantas ofertas a curadoria IA
  aprova e seleciona por ciclo — o teto só evita rajada quando há muitas ofertas elegíveis
  de uma vez (ex.: após reativar um canal parado).
- O piso (`channel_items_min_per_cycle=1`) é apenas informativo: se não houver itens
  elegíveis, o ciclo não força envio — só registra `channel_cadence.below_floor` no log.

## Verificação

- Rodar um ciclo real pequeno e medir o intervalo entre `sent_at` consecutivos:
  `select sent_at from distribution_delivery where social_channel_id=2 order by sent_at desc limit 5`
  — a diferença entre linhas deve respeitar `wa_min_interval_seconds`.
- Forçar um lote grande (mais itens elegíveis que `channel_items_max_per_cycle`) e conferir
  no stdout a mensagem `Cadência: lote reduzido de N para M`.
- Derrubar a sessão do WhatsApp (parar o Evolution adapter) e rodar 1 ciclo: o log deve
  mostrar `whatsapp_session.precheck_failed` (ou `whatsapp_session.dropped_mid_batch` se a
  queda ocorrer no meio do lote) e **não** uma sequência de dezenas de `FAILED` contíguos —
  ver Tarefa 1.3 (`SessaoIndisponivelError`).

---

# Runbook — Ingestão de vendas do painel ML (`ingest-ml-afiliados.timer`)

Traz do painel de afiliados do Mercado Livre as vendas **uma a uma**, com status
e motivo de rejeição, para `MLAffiliateSale`. Detalhes de projeto, limites do
endpoint e a recalibragem de `max_price` que ela viabilizou estão em
`docs/INGESTAO_PAINEL_ML_2026-08-23.md`.

## Cadência

Semanal, segunda 06:20 (`RandomizedDelaySec=15min`, `Persistent=true`), janela de
45 dias **propositalmente sobreposta**: venda entra como `IN_REVIEW` e só resolve
semanas depois, e a ingestão é idempotente por `sale_id`.

## Instalação (systemd --user)

```bash
systemctl --user daemon-reload
systemctl --user enable --now ingest-ml-afiliados.timer
```

Verificar:

```bash
systemctl --user list-timers ingest-ml-afiliados.timer
tail -n 50 logs/ingest-ml-afiliados.log
```

## Dependência crítica: `ML_COOKIE`

Usa o mesmo cookie do scraper de ofertas. **Cookie vencido derruba as duas
coisas** — a ingestão levanta `MLAffiliateAuthError` e dispara alerta de operador
(`categoria='ml_cookie_expirado'`) antes de falhar. Se este timer começar a
falhar por autenticação, verificar a coleta de ML no mesmo movimento.

## Validar sem persistir

```bash
python3 manage.py ingest_ml_affiliate_sales --days 7 --dry-run
```

## Rollback rápido

```bash
systemctl --user disable --now ingest-ml-afiliados.timer
```

Nenhum dado já ingerido é afetado.

## Cuidado ao ler os números

Compra própria marcada automaticamente vem **só** de status `REJECTED`; compra da
casa ainda `IN_REVIEW` não é detectada e precisa de marcação manual no Admin — que
a rotina nunca sobrescreve.
