# Contrato técnico — Evolution Adapter (compatível com wa_service)

> Escopo: S0.4/S1 do plano `docs/PLANO_MIGRACAO_EVOLUTION_API.md`.
> Este contrato congela a interface HTTP que o Django já consome do `wa_service` e que o novo `evolution_adapter/` deve expor. A troca de provedor deve ser feita por `base_url`/feature flag, sem alterar os payloads do Django.

## 1. Princípios

- O `wa_service/` Baileys permanece intacto e é fallback.
- O `evolution_adapter/` fala com a Evolution API e expõe a mesma interface local do `wa_service` para o Django.
- Segredos nunca entram em código: `EVOLUTION_API_KEY` apenas via ambiente.
- Envio deve usar a instância `EVOLUTION_INSTANCIA_ENVIO`.
- Observer/webhook deve usar a instância `EVOLUTION_INSTANCIA_OBSERVER`.
- Grupos podem chegar por nome ou JID nos endpoints de envio; o adapter resolve nome→JID usando `EVOLUTION_GROUP_MAP_PATH`/`EVOLUTION_GROUP_MAP_JSON`.
- Imagem para Evolution API pode ser URL pública ou base64 em `sendMedia.media`; URLs sem extensão explícita (caso comum em Shopee/CDN) devem ser baixadas pelo adapter e enviadas como base64 com `mimetype`/`fileName` explícitos.

## 2. Variáveis do adapter

| Variável | Obrigatória | Default | Uso |
|---|---:|---|---|
| `EVOLUTION_ADAPTER_HOST` | não | `127.0.0.1` | bind local seguro |
| `EVOLUTION_ADAPTER_PORT` | não | `8788` | porta do adapter |
| `EVOLUTION_BASE_URL` | sim para envio real | — | base URL da Evolution API |
| `EVOLUTION_API_KEY` | sim para envio real | — | header `apikey` |
| `EVOLUTION_INSTANCIA_ENVIO` | não | `descontos_envio` | instância de envio |
| `EVOLUTION_INSTANCIA_OBSERVER` | não | `descontos_observer` | instância observer |
| `EVOLUTION_GROUP_MAP_PATH` | não | `evolution_adapter/config/group_map.json` | mapa nome→JID e JID→subject |
| `EVOLUTION_GROUP_MAP_JSON` | não | — | mapa inline, tem precedência sobre arquivo |
| `EVOLUTION_OBSERVER_BUFFER_PATH` | não | `evolution_adapter/data/observer_buffer.json` | buffer persistente de mensagens normalizadas |
| `WA_OBSERVER_ENABLED` | não | `false` | habilita collect/groups |
| `WA_OBSERVER_GROUP_JIDS` | sim para observer | — | allowlist de JIDs separados por vírgula |
| `WA_OBSERVER_LOOKBACK_HOURS` | não | `24` | janela do collect |
| `WA_OBSERVER_MAX_MESSAGES_PER_GROUP` | não | `300` | limite por grupo no collect |
| `WA_OBSERVER_SENDER_HASH_SALT` | não | `descontos-bot-observer` | compatibilidade de hash |

Formato do mapa de grupos:

```json
{
  "Nome exato do grupo": "120363000000000001@g.us",
  "Outro grupo": { "jid": "120363000000000002@g.us", "subject": "Outro grupo" }
}
```

## 3. GET /health

Endpoint novo do adapter para readiness local, sem contato com WhatsApp real.

Resposta `200`:

```json
{
  "ok": true,
  "service": "evolution_adapter"
}
```

## 4. GET /status

Compatível com `wa_service` para clientes que checam conexão.

Resposta sem Evolution configurado:

```json
{
  "connected": false,
  "jid": null,
  "provider": "evolution"
}
```

Resposta consulta `/instance/connectionState/{EVOLUTION_INSTANCIA_ENVIO}` na Evolution API. `connected=true` exige `state=open`; config presente não basta.

## 5. POST /send-message

Envia uma mensagem única para grupo. É o endpoint usado por `apps/distribution/services/whatsapp_client.py::WhatsAppClient.send_message`.

### Request

```json
{
  "destination": "Nome exato do grupo ou 120363000000000001@g.us",
  "message": "texto da oferta",
  "image_url": "https://exemplo.com/imagem.jpg"
}
```

Campos:

- `destination` obrigatório string.
- `message` obrigatório string.
- `image_url` opcional string; quando presente, adapter chama `sendMedia`.

### Chamadas Evolution

Texto:

```http
POST /message/sendText/{EVOLUTION_INSTANCIA_ENVIO}
apikey: <EVOLUTION_API_KEY>
Content-Type: application/json

{"number":"120363000000000001@g.us","text":"texto da oferta"}
```

Imagem:

```http
POST /message/sendMedia/{EVOLUTION_INSTANCIA_ENVIO}
apikey: <EVOLUTION_API_KEY>
Content-Type: application/json

{
  "number": "120363000000000001@g.us",
  "mediatype": "image",
  "mimetype": "image/jpeg",
  "caption": "texto da oferta",
  "media": "https://exemplo.com/imagem.jpg",
  "fileName": "offer.jpg"
}
```

### Resposta adapter `200`

```json
{
  "success": true,
  "message_id": "abc123",
  "sent_at": "2026-04-29T10:30:00.000Z"
}
```

`message_id` deve ser extraído de campos conhecidos da Evolution quando possível (`key.id`, `id`, `messageId`); vazio é aceito pelo cliente atual, mas deve ser tratado como alerta operacional.

### Erros

- `400 {"error":"Campo 'destination' é obrigatório (string)"}`.
- `400 {"error":"Campo 'message' é obrigatório (string)"}`.
- `400 {"error":"Campo 'image_url' deve ser string quando informado"}`.
- `500 {"error":"..."}` para falha de resolução de grupo ou chamada Evolution.

## 6. POST /send

Contrato legado de lote usado pelo `wa_service`.

### Request

```json
{
  "target": "Nome exato do grupo ou 120363000000000001@g.us",
  "items": [
    {
      "id": "offer-123",
      "image_path": "/caminho/local/imagem.jpg",
      "text_path": "/caminho/local/legenda.txt"
    }
  ]
}
```

### Preparação S1 segura

A Evolution API não recebe caminho local; por isso, neste adapter `/send` só aceita `items[].image_url` ou `items[].media_url` além de `text`/`message`/`caption`. O formato `image_path`/`text_path` permanece legado Baileys e retorna falha por item.

Resposta parcial compatível:

```json
{
  "sent": 1,
  "errors": 1,
  "failures": [
    {"id":"offer-124","reason":"item sem image_url/media_url para Evolution"}
  ]
}
```

## 7. POST /webhook/whatsapp

Endpoint novo do adapter. A Evolution `descontos_observer` deve apontar `MESSAGES_UPSERT` para este caminho.

### Request esperado

O payload real da Evolution v2.3.4 foi validado em runtime. O adapter aceita envelopes comuns e procura uma mensagem em:

- `body.data`;
- `body.message`;
- cada item de `body.data.messages`;
- cada item de `body.messages`.

A mensagem normalizável deve se aproximar do objeto Baileys:

```json
{
  "key": {
    "remoteJid": "120363000000000001@g.us",
    "id": "MSG1",
    "participant": "5511999999999@s.whatsapp.net"
  },
  "messageTimestamp": 1780000000,
  "message": {
    "extendedTextMessage": { "text": "Oferta https://exemplo.com" }
  }
}
```

### Resposta

```json
{
  "accepted": true,
  "recorded": 1
}
```

Se observer desabilitado/fora da allowlist, `recorded` pode ser `0` e o webhook ainda responde `200` para evitar retry infinito.

## 8. POST /observer/collect

Compatível com `apps/market_intel/services/whatsapp_observer_client.py::WhatsAppObserverClient.collect`.

Resposta:

```json
{
  "enabled": true,
  "messages": [
    {
      "message_id": "MSG1",
      "group_jid": "120363000000000001@g.us",
      "group_subject": "Ofertas A",
      "sender_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "sent_at": "2026-06-11T23:20:00.000Z",
      "text": "Oferta Amazon R$ 99 https://exemplo.com",
      "has_image": false,
      "urls": ["https://exemplo.com"],
      "raw_type": "extendedTextMessage",
      "collected_at": "2026-06-11T23:30:00.000Z",
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

Campos obrigatórios do schema atual: `message_id`, `group_jid`, `group_subject`, `sender_hash`, `sent_at`, `text`, `has_image`, `urls`, `raw_type`, `collected_at`, `reacoes`, `visualizacoes`, `encaminhamentos`, `comentarios`, `repostado`, `qtd_repostagens`, `fixado`.

## 9. GET /observer/groups

Compatível com `WhatsAppObserverClient.groups`.

Resposta:

```json
{
  "enabled": true,
  "groups": [
    {"jid":"120363000000000001@g.us","subject":"Ofertas A"}
  ]
}
```

O adapter retorna a interseção entre `WA_OBSERVER_GROUP_JIDS` e o mapa de grupos local.

## 10. Arquivos/funções atuais relacionados

- Envio Django: `apps/distribution/services/whatsapp_client.py`
  - `WhatsAppClient.__init__`: hoje lê `settings.WA_SERVICE_URL`.
  - `WhatsAppClient.get_status`: `GET /status`.
  - `WhatsAppClient.send_message`: `POST /send-message`.
- Observer Django: `apps/market_intel/services/whatsapp_observer_client.py`
  - `WhatsAppObserverClient.groups`: `GET /observer/groups`.
  - `WhatsAppObserverClient.collect`: `POST /observer/collect`.
- Serviço Baileys atual: `wa_service/src/server.ts`
  - `POST /send`, `POST /send-message`, `POST /observer/collect`, `GET /observer/groups`, `GET /status`.
- Resolução/envio Baileys: `wa_service/src/wa.ts`
  - `resolveGroupJid`, `sendText`, `sendBatch`, `listObserverGroups`, `collectObservedMessages`.
- Normalização observer Baileys: `wa_service/src/observer.ts`
  - `normalizeIncomingMessage`, `recordObservedMessage`, `collectObservedMessages`, `listObserverGroups`.

## 11. Pendências antes de cutover final

- Payload real `MESSAGES_UPSERT` validado com Evolution API v2.3.4.
- JIDs reais dos grupos resolvidos e mapa local `evolution_adapter/config/group_map.json` preenchido fora do git.
- `/send` legado com arquivos locais rejeitado no fluxo Evolution; envio em lote exige URL pública (`image_url`/`media_url`) e texto inline.
- Seleção `WA_PROVIDER`/`EVOLUTION_ADAPTER_URL` adicionada nos clientes Django, mantendo default Baileys.
