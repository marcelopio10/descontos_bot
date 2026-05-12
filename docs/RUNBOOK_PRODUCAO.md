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
- [ ] Links Amazon `/r?slug=...` mostram disclosure e redirecionam para Amazon mantendo `tag=descontos.bot-20`.
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
