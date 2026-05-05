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
```

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
- Sessões do WhatsApp ficam em `wa_service/auth_state/` e são ignoradas pelo git.
- A prévia operacional está documentada em `docs/DRY_RUN.md`.
