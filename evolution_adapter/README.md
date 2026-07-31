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
WA_OBSERVER_GROUP_JIDS="<ver cofre: observer-group-jids>" \
npm start
```

Por padrão o adapter sobe em `127.0.0.1:8788`.

## Provider de saída de ofertas

O envio direto pela Evolution continua sendo o comportamento padrão:

```bash
WA_OUTBOUND_PROVIDER=evolution
```

Para homologar a fila central, configure `WA_OUTBOUND_PROVIDER=router`,
`WA_ROUTER_BASE_URL` e `WA_ROUTER_TOKEN`. Nesse modo, `/send-message` exige
`idempotency_key`; cada item de `/send` exige `idempotency_key`. O adapter envia
`type=offer`, texto e mídia (quando informada) para `POST /v1/outbound`. O tipo
`offer` recebe prioridade 3 no roteador.

O destino sempre é resolvido e conferido no mapa local antes da chamada. O
payload interno leva somente o alias simbólico usado no mapa; entradas em
formato JID são rejeitadas mesmo quando conhecidas localmente. O roteador resolve
o alias novamente no seu registry, mantendo a autorização em duas camadas.

Falhas, timeouts ou respostas inválidas do roteador retornam um erro sanitizado
e **não** acionam fallback automático para Evolution, evitando duplicidade. O
cliente não registra JID, texto da oferta ou token em logs. A coleta observer
(`/webhook/whatsapp` e `/observer/collect`) não depende do provider de saída.

Os testes usam apenas servidores HTTP falsos. Para o teste de contrato em
dry-run, mantenha o worker de envio desabilitado e confirme no roteador que a
oferta foi enfileirada com prioridade 3 antes de qualquer cutover.

## Mapa de grupos

Crie `config/group_map.json` localmente (ignorado pelo git) a partir de `config/group_map.example.json`:

```json
{
  "Nome exato do grupo": {
    "jid": "<ver cofre: nome-grupo-jid>",
    "subject": "Nome exato do grupo",
    "router_alias": "alias-opaco-do-grupo"
  }
}
```

`router_alias` é obrigatório quando `WA_OUTBOUND_PROVIDER=router`: use somente
letras minúsculas, dígitos, `_` e `-`, começando por letra. O nome e o JID do
grupo nunca atravessam a API interna; apenas esse alias é enviado.

Contrato completo: `docs/EVOLUTION_ADAPTER_CONTRACT.md`.

## Validação local

- `/send-message` com texto e imagem validado contra `descontos.bot - Homologação` via Evolution API v2.3.4.
- `/webhook/whatsapp` configurado na instância `descontos_observer` com evento `MESSAGES_UPSERT`.
- `/observer/collect` validado com schema de 17 campos compatível com o pipeline Market Intel.
