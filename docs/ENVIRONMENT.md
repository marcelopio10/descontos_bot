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

## Shopee Affiliate Open API (Sprint 7B)

Conector oficial GraphQL. Detalhes de operação em `docs/SHOPEE_AFFILIATE_API.md`.

```env
SHOPEE_AFFILIATE_API_URL=https://open-api.affiliate.shopee.com.br/graphql
SHOPEE_AFFILIATE_APP_ID=
SHOPEE_AFFILIATE_SECRET=
SHOPEE_AFFILIATE_DEFAULT_LIMIT=50
SHOPEE_AFFILIATE_TIMEOUT_SECONDS=20
SHOPEE_AFFILIATE_MAX_RETRIES=3
SHOPEE_AFFILIATE_ENABLED=false
```

- `SHOPEE_AFFILIATE_ENABLED=false` mantém o conector travado: `collect_shopee_offers --save` aborta; `--dry-run` e testes mockados continuam funcionando.
- `SHOPEE_AFFILIATE_APP_ID`/`SHOPEE_AFFILIATE_SECRET` só no `.env` local, nunca no Git nem no vault.

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
