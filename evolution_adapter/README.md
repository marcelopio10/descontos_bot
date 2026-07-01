# evolution_adapter

Adapter HTTP local para migração do `wa_service`/Baileys para Evolution API.

Escopo atual: adapter de compatibilidade para envio e observer via Evolution API, mantendo `wa_service` como fallback.

## Rodar testes locais

```bash
cd evolution_adapter
npm test
```

Os testes usam um servidor Evolution fake em loopback e não exigem segredo, WhatsApp real ou Docker.

## Iniciar manualmente

```bash
cd evolution_adapter
EVOLUTION_BASE_URL="http://127.0.0.1:8081" \
EVOLUTION_API_KEY="<cofre>" \
WA_OBSERVER_ENABLED=true \
WA_OBSERVER_GROUP_JIDS="120363000000000000@g.us" \
npm start
```

Por padrão o adapter sobe em `127.0.0.1:8788`.

## Mapa de grupos

Crie `config/group_map.json` localmente (ignorado pelo git) a partir de `config/group_map.example.json`:

```json
{
  "Nome exato do grupo": {
    "jid": "120363000000000000@g.us",
    "subject": "Nome exato do grupo"
  }
}
```

Contrato completo: `docs/EVOLUTION_ADAPTER_CONTRACT.md`.

## Validação local

- `/send-message` com texto e imagem validado contra `descontos.bot - Homologação` via Evolution API v2.3.4.
- `/webhook/whatsapp` configurado na instância `descontos_observer` com evento `MESSAGES_UPSERT`.
- `/observer/collect` validado com schema de 17 campos compatível com o pipeline Market Intel.
