# Contrato alvo — wa_service compatível com evolution_adapter

Fonte congelada em S0.4 a partir de:

- `wa_service/src/server.ts`
- `wa_service/src/wa.ts`
- `wa_service/src/observer.ts`
- `apps/distribution/services/whatsapp_client.py`
- `apps/market_intel/services/whatsapp_observer_client.py`

Objetivo: permitir que um `evolution_adapter` implemente a mesma interface HTTP hoje consumida pelo Django, mantendo `wa_service`/Baileys como fallback.

## Base URL

Atual:

- Django usa `settings.WA_SERVICE_URL` quando configurado.
- Fallback atual: `http://127.0.0.1:8787`.

Alvo da migração:

- `WA_PROVIDER=baileys` mantém `WA_SERVICE_URL`/porta 8787.
- `WA_PROVIDER=evolution` deve apontar os clientes Django para `EVOLUTION_ADAPTER_URL`.

## GET /status

### Resposta esperada

```json
{
  "connected": true,
  "jid": "<jid-ou-identificador-da-instancia>"
}
```

### Semântica

- `connected=true` quando a instância de envio estiver em `connectionState=open`.
- `jid` pode ser o JID retornado pelo provider ou, se a Evolution API não expuser o JID de forma estável, o nome da instância resolvida.

## POST /send-message

Usado por `apps/distribution/services/whatsapp_client.py`.

### Request

```json
{
  "destination": "nome do grupo ou jid@g.us",
  "message": "texto/caption",
  "image_url": "https://..." 
}
```

`image_url` é opcional.

### Validação

- `destination`: obrigatório, string.
- `message`: obrigatório, string não vazia.
- `image_url`: opcional, string.

### Comportamento Baileys atual

- Resolve nome de grupo por `groupFetchAllParticipating()` quando `destination` não termina com `@g.us`.
- Aceita JID direto terminado em `@g.us`.
- Se `image_url` existe, envia imagem por URL com `caption=message`.
- Sem `image_url`, envia texto.

### Mapeamento Evolution API

- Texto: `POST /message/sendText/{EVOLUTION_INSTANCIA_ENVIO}`

```json
{
  "number": "<jid@g.us>",
  "text": "<message>"
}
```

- Imagem: `POST /message/sendMedia/{EVOLUTION_INSTANCIA_ENVIO}`

```json
{
  "number": "<jid@g.us>",
  "mediatype": "image",
  "mimetype": "image/jpeg",
  "caption": "<message>",
  "media": "<image_url>",
  "fileName": "oferta.jpg"
}
```

### Resposta esperada pelo Django

```json
{
  "success": true,
  "message_id": "<id>",
  "sent_at": "2026-06-27T12:00:00.000Z"
}
```

Em erro, retornar HTTP 4xx/5xx com:

```json
{"error":"mensagem legível"}
```

## POST /send

Endpoint legado de lote do `wa_service`.

### Request

```json
{
  "target": "nome do grupo ou jid@g.us",
  "items": [
    {
      "id": "offer-id",
      "image_path": "caminho local",
      "text_path": "caminho local"
    }
  ]
}
```

### Resposta atual

```json
{
  "sent": 1,
  "errors": 0,
  "failures": []
}
```

### Observação para Evolution

A Evolution API envia mídia por URL pública ou base64. O contrato atual de `/send` usa arquivo local (`image_path`). Para manter compatibilidade, o adapter deve escolher uma das opções:

1. Converter arquivo local para base64 antes de chamar `sendMedia`; ou
2. Retornar erro explícito se o item não puder ser convertido; ou
3. Evoluir o produtor para usar `/send-message` com `image_url` pública.

Para migração incremental, implementar conversão base64 é o caminho de menor impacto no contrato.

## GET /observer/groups

Usado por `WhatsAppObserverClient.groups()`.

### Resposta esperada

```json
{
  "enabled": true,
  "groups": [
    {"jid":"1203...@g.us","subject":"Nome do grupo"}
  ]
}
```

### Semântica

- Respeitar `WA_OBSERVER_ENABLED`.
- Retornar apenas grupos allowlisted por `WA_OBSERVER_GROUP_JIDS`.
- Nunca retornar participantes, telefones ou metadados sensíveis.

## POST /observer/collect

Usado por `WhatsAppObserverClient.collect()`.

### Request

Corpo vazio ou `{}`.

### Resposta esperada

```json
{
  "enabled": true,
  "messages": [
    {
      "message_id": "...",
      "group_jid": "1203...@g.us",
      "group_subject": "Nome do grupo",
      "sender_hash": "sha256",
      "sent_at": "2026-06-27T12:00:00.000Z",
      "text": "texto normalizado",
      "has_image": false,
      "urls": ["https://..."],
      "raw_type": "conversation",
      "collected_at": "2026-06-27T12:00:01.000Z",
      "reacoes": null,
      "visualizacoes": null,
      "encaminhamentos": null,
      "comentarios": null,
      "repostado": null,
      "qtd_repostagens": null,
      "fixado": null
    }
  ]
}
```

## POST /webhook/whatsapp

Novo endpoint do `evolution_adapter`.

### Entrada

Payload bruto da Evolution API para evento `MESSAGES_UPSERT`. O formato exato deve ser capturado em runtime antes de fechar o mapeamento definitivo.

### Saída

```json
{"ok":true,"stored":1,"duplicate":0,"ignored":0}
```

### Regras

- Aceitar somente eventos da instância `EVOLUTION_INSTANCIA_OBSERVER`.
- Aplicar allowlist antes de gravar no buffer.
- Normalizar para o mesmo schema de 24 campos do `wa_service/src/observer.ts`.
- Deduplicar por `(group_jid, message_id)`.
- Ordenar coleta por `sent_at`.
- Persistir buffer em JSON, equivalente ao `WA_OBSERVER_BUFFER_PATH` atual.

## Variáveis de configuração

- `WA_PROVIDER=baileys|evolution`
- `WA_SERVICE_URL=http://127.0.0.1:8787`
- `EVOLUTION_ADAPTER_URL=http://127.0.0.1:<porta>`
- `EVOLUTION_ADAPTER_PORT=<porta>`
- `EVOLUTION_BASE_URL=http://localhost:8081`
- `EVOLUTION_API_KEY=<ver cofre: evolution-api>`
- `EVOLUTION_INSTANCIA_ENVIO=descontos_envio`
- `EVOLUTION_INSTANCIA_OBSERVER=descontos_observer`
- `EVOLUTION_GROUP_MAP_PATH=<arquivo local ignorado>` ou `EVOLUTION_GROUP_MAP_JSON=<json>`
- `WA_OBSERVER_ENABLED=true|false`
- `WA_OBSERVER_GROUP_JIDS=jid1@g.us,jid2@g.us`
- `WA_OBSERVER_LOOKBACK_HOURS=24`
- `WA_OBSERVER_MAX_MESSAGES_PER_GROUP=300`
- `WA_OBSERVER_SENDER_HASH_SALT=<ver cofre>`

## Critérios de paridade

- `npm test` em `wa_service`: 41 testes passando no baseline atual.
- `manage.py check`: sem issues no baseline atual.
- `GET /status`, `POST /send-message`, `POST /observer/collect` e `GET /observer/groups` devem manter formatos consumidos pelos clientes Python existentes.
- Nenhum segredo em código, docs ou logs.
