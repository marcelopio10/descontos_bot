# Contrato do wa_service — descontos.bot

O `wa_service/` é o serviço Node.js auxiliar responsável pelo envio no WhatsApp via Baileys. O Django deve tratar este serviço como processo externo local e consumir somente o contrato HTTP documentado aqui.

## Runtime

- Node.js 20 LTS.
- Porta local fixa atual: `8787`.
- Base URL: `http://127.0.0.1:8787`.
- Auth state local: `wa_service/auth_state/`.
- O diretório `wa_service/auth_state/` contém sessão WhatsApp e não deve ser versionado.

## Comandos

Instalar dependências:

```bash
cd wa_service
npm install
```

Iniciar em desenvolvimento:

```bash
cd wa_service
npm run dev
```

Iniciar pelo script principal:

```bash
cd wa_service
npm start
```

Executar suíte existente do serviço:

```bash
cd wa_service
npm test
```

## Pareamento

Ao iniciar, o serviço tenta conectar ao WhatsApp. Se não houver sessão válida, ele imprime um QR code no terminal. O operador deve escanear o QR code com o celular.

## GET /status

Retorna o estado atual da conexão.

### Resposta conectada

```json
{
  "connected": true,
  "jid": "5511999999999:1@s.whatsapp.net"
}
```

### Resposta desconectada

```json
{
  "connected": false,
  "jid": null
}
```

## POST /send

Envia um lote de ofertas para um grupo WhatsApp.

### Request

```json
{
  "target": "Nome exato do grupo",
  "items": [
    {
      "id": "offer-123",
      "image_path": "/caminho/absoluto/imagem.jpg",
      "text_path": "/caminho/absoluto/mensagem.txt"
    }
  ]
}
```

### Campos

- `target`: nome exato do grupo participante do WhatsApp.
- `items`: array não vazio de itens.
- `items[].id`: identificador local usado nos logs e falhas.
- `items[].image_path`: caminho absoluto da imagem que será enviada.
- `items[].text_path`: caminho absoluto do arquivo de texto usado como legenda.

### Resposta de sucesso

```json
{
  "sent": 1,
  "errors": 0,
  "failures": []
}
```

### Erros de validação

Quando `target` está ausente:

```json
{
  "error": "Campo 'target' é obrigatório (string)"
}
```

Quando `items` está ausente ou vazio:

```json
{
  "error": "Campo 'items' deve ser array não-vazio"
}
```

### Serviço desconectado

Quando o WhatsApp ainda não está conectado:

```json
{
  "error": "WhatsApp não conectado. Aguarde o pareamento via QR."
}
```

Status HTTP: `503`.

## Comportamento Operacional

- O serviço resolve o JID do grupo pelo nome exato informado em `target`.
- O serviço envia imagem com legenda.
- O intervalo entre mensagens é aplicado dentro do `wa_service`, com jitter atual entre 5,5s e 9,5s.
- Falhas por item são acumuladas em `failures`.
- O Django deve registrar `Delivery` como `sent` somente para itens confirmados como enviados.
- O Django deve bloquear qualquer chamada real a `/send` durante a janela 00:00-06:00 BRT.

## POST /send-message

Envia uma mensagem de texto simples para um grupo WhatsApp. Este é o contrato usado pelo Django no MVP, porque a curadoria atual gera apenas texto com link final.

### Request

```json
{
  "destination": "Nome exato do grupo",
  "message": "texto da mensagem"
}
```

### Campos

- `destination`: nome exato do grupo participante do WhatsApp.
- `message`: texto em pt-BR que será enviado ao grupo.

### Resposta de sucesso

```json
{
  "success": true,
  "message_id": "abc123",
  "sent_at": "2026-04-29T10:30:00.000Z"
}
```

### Erros de validação

Quando `destination` está ausente:

```json
{
  "error": "Campo 'destination' é obrigatório (string)"
}
```

Quando `message` está ausente:

```json
{
  "error": "Campo 'message' é obrigatório (string)"
}
```

### Serviço desconectado

Quando o WhatsApp ainda não está conectado:

```json
{
  "error": "WhatsApp não conectado. Aguarde o pareamento via QR."
}
```

Status HTTP: `503`.
