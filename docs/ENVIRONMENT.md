# Ambiente Local — descontos.bot

As credenciais devem ficar em `.env` local e nunca devem ser versionadas.

## Variáveis previstas

```env
DJANGO_SECRET_KEY=troque-este-valor-localmente
DJANGO_DEBUG=true
WA_SERVICE_BASE_URL=http://127.0.0.1:8787
WA_TARGET=grupo-ofertas-homologacao
ML_AFFILIATE_ID=
AMAZON_AFFILIATE_TAG=
DRY_RUN=true
PUBLISH_OFFERS_AFTER_CAPTURE=true
PUBLISH_OFFERS_PUSH=true
PUBLISH_OFFERS_BRANCH=main
OFFERS_JSON_OUTPUT_PATH=site/offers.json
```

## Login do site privado (Vercel — Sprint 7A)

Protege `/dashboard`, `/inteligencia` e os JSONs sensíveis (`affiliate-summary.json`, `market-intel.json`). Operador único. Defina estas variáveis no `.env` local **e** no painel Environment Variables do Vercel.

```env
SITE_AUTH_USER=operador
SITE_AUTH_PASSWORD_HASH=
SITE_AUTH_SECRET=
SITE_AUTH_SESSION_TTL_SECONDS=28800
```

- `SITE_AUTH_SECRET` — segredo forte e aleatório (ex.: `openssl rand -hex 32`). Assina a sessão e ancora o hash da senha.
- `SITE_AUTH_PASSWORD_HASH` — **não é a senha**. É `HMAC-SHA256(senha, SITE_AUTH_SECRET)` em hex, gerado por:

  ```bash
  SITE_AUTH_SECRET='<o-mesmo-secret>' node site/scripts/hash-password.mjs 'minha-senha-forte'
  ```

  Trocar a senha = regerar o hash. Trocar o `SITE_AUTH_SECRET` invalida todas as sessões e exige regerar o hash.
- `SITE_AUTH_SESSION_TTL_SECONDS` — validade da sessão; default 28800 (8h).
- Falha fechada: sem essas variáveis configuradas, `/api/login` responde 503 e o middleware bloqueia as rotas privadas.

## Dados iniciais

Após aplicar migrations, execute:

```bash
python3 manage.py seed_initial_data --target "Nome exato do grupo WhatsApp"
```

Se ainda não houver grupo de homologação definido pelo PO, mantenha o alvo padrão:

```bash
python3 manage.py seed_initial_data
```

## Observações

- `WA_TARGET` deve corresponder ao nome exato do grupo que o `wa_service` consegue resolver.
- `DRY_RUN=true` deve ser mantido até o PO autorizar envio real.
- `PUBLISH_OFFERS_AFTER_CAPTURE=false` desativa a publicação automática após captura.
- `PUBLISH_OFFERS_PUSH=false` atualiza `site/offers.json` localmente quando houver diff, sem commit nem push.
- `PUBLISH_OFFERS_BRANCH` define a branch usada no `git push`; o padrão é `main`.
- `OFFERS_JSON_OUTPUT_PATH` define o `offers.json` consumido pelo site estático.
- Sessões do WhatsApp do Baileys ficam em `wa_service/auth_state/` por padrão (`WA_AUTH_DIR` pode sobrescrever) e são ignoradas pelo git; o `wa_session/` da raiz é perfil de navegador legado.
- A prévia operacional está documentada em `docs/DRY_RUN.md`.
