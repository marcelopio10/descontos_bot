import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import http from 'node:http';

import { getConfig } from '../src/config.js';
import { createApp } from '../src/server.js';

let fakeEvolution;
let fakeEvolutionUrl;
let fakeRouter;
let fakeRouterUrl;
let adapter;
let adapterUrl;
let tmp;
const calls = [];
const routerCalls = [];

before(async () => {
  tmp = await mkdtemp(path.join(tmpdir(), 'evolution-adapter-test-'));
  fakeEvolution = http.createServer(async (req, res) => {
    if (req.method === 'GET' && req.url === '/image-no-extension') {
      res.writeHead(200, { 'Content-Type': 'image/jpeg' });
      res.end(Buffer.from('fake-jpeg-bytes'));
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf-8');
    calls.push({ method: req.method, url: req.url, headers: req.headers, body: body ? JSON.parse(body) : null });
    res.writeHead(200, { 'Content-Type': 'application/json' });
    if (req.method === 'GET' && req.url?.startsWith('/instance/connectionState/')) {
      res.end(JSON.stringify({ instance: { state: 'open' } }));
      return;
    }
    res.end(JSON.stringify({ key: { id: 'EVO123' } }));
  });
  await listen(fakeEvolution, '127.0.0.1', 0);
  fakeEvolutionUrl = `http://127.0.0.1:${fakeEvolution.address().port}`;

  fakeRouter = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf-8');
    routerCalls.push({ method: req.method, url: req.url, headers: req.headers, body: body ? JSON.parse(body) : null });
    res.writeHead(202, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ queued: true, priority: 3 }));
  });
  await listen(fakeRouter, '127.0.0.1', 0);
  fakeRouterUrl = `http://127.0.0.1:${fakeRouter.address().port}`;

  const config = getConfig({
    EVOLUTION_BASE_URL: fakeEvolutionUrl,
    EVOLUTION_API_KEY: 'test-key',
    EVOLUTION_GROUP_MAP_JSON: JSON.stringify({ 'Grupo Teste': { jid: '120363000000001@g.us', subject: 'Grupo Teste' } }),
    EVOLUTION_OBSERVER_BUFFER_PATH: path.join(tmp, 'observer_buffer.json'),
    WA_OBSERVER_ENABLED: 'true',
    WA_OBSERVER_GROUP_JIDS: '120363000000001@g.us,120363000000999@g.us',
    WA_OBSERVER_SENDER_HASH_SALT: 'salt-test',
  });
  adapter = createApp({ config });
  await listen(adapter, '127.0.0.1', 0);
  adapterUrl = `http://127.0.0.1:${adapter.address().port}`;
});

after(async () => {
  await close(adapter);
  await close(fakeRouter);
  await close(fakeEvolution);
  await rm(tmp, { recursive: true, force: true });
});

test('GET /health responde sem depender de Evolution real', async () => {
  const response = await fetch(`${adapterUrl}/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, service: 'evolution_adapter' });
});

test('GET /status consulta connectionState real da Evolution', async () => {
  const response = await fetch(`${adapterUrl}/status`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { connected: true, jid: 'descontos_envio', provider: 'evolution' });
  assert.equal(calls.at(-1).url, '/instance/connectionState/descontos_envio');
});

test('POST /send-message resolve nome para JID e chama sendText', async () => {
  const response = await post('/send-message', { destination: 'Grupo Teste', message: 'Oferta' });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).message_id, 'EVO123');
  const call = calls.at(-1);
  assert.equal(call.url, '/message/sendText/descontos_envio');
  assert.equal(call.headers.apikey, 'test-key');
  assert.deepEqual(call.body, { number: '120363000000001@g.us', text: 'Oferta' });
});

test('provider evolution é o default e preserva envio direto', () => {
  assert.equal(getConfig({}).outboundProvider, 'evolution');
});

test('provider router enfileira type=offer sem fallback para Evolution', async () => {
  const routerConfig = createRouterConfig('observer_buffer_router.json');
  const routerAdapter = createApp({ config: routerConfig });
  await listen(routerAdapter, '127.0.0.1', 0);
  try {
    const evolutionCallsBefore = calls.length;
    const response = await fetch(`http://127.0.0.1:${routerAdapter.address().port}/send-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        destination: 'Grupo Teste',
        message: 'Oferta roteada',
        image_url: 'https://example.com/roteada.jpg',
        idempotency_key: 'offer:server:1',
      }),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { queued: true, priority: 3 });
    assert.equal(calls.length, evolutionCallsBefore);
    assert.deepEqual(routerCalls.at(-1).body, {
      type: 'offer',
      destination: 'group-fixture',
      idempotency_key: 'offer:server:1',
      text: 'Oferta roteada',
      media_url: 'https://example.com/roteada.jpg',
    });
  } finally {
    await close(routerAdapter);
  }
});

test('provider router enfileira lote com chave por oferta', async () => {
  const routerConfig = createRouterConfig('observer_buffer_router_batch.json');
  const routerAdapter = createApp({ config: routerConfig });
  await listen(routerAdapter, '127.0.0.1', 0);
  try {
    const response = await fetch(`http://127.0.0.1:${routerAdapter.address().port}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: 'Grupo Teste',
        items: [{
          id: '42',
          idempotency_key: 'offer:batch:42',
          text: 'Oferta em lote',
          image_url: 'https://example.com/lote.jpg',
        }],
      }),
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { sent: 1, errors: 0, failures: [] });
    assert.equal(routerCalls.at(-1).body.idempotency_key, 'offer:batch:42');
    assert.equal(routerCalls.at(-1).body.type, 'offer');
  } finally {
    await close(routerAdapter);
  }
});

test('falha do roteador retorna erro controlado sem fallback direto', async () => {
  const failingRouter = http.createServer(async (req, res) => {
    for await (const _chunk of req) {
      // Drena a requisição sem registrar payload.
    }
    res.writeHead(503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'detalhe interno sensível' }));
  });
  await listen(failingRouter, '127.0.0.1', 0);
  const routerConfig = createRouterConfig(
    'observer_buffer_router_failure.json',
    `http://127.0.0.1:${failingRouter.address().port}`,
  );
  const routerAdapter = createApp({ config: routerConfig });
  await listen(routerAdapter, '127.0.0.1', 0);
  try {
    const evolutionCallsBefore = calls.length;
    const response = await fetch(`http://127.0.0.1:${routerAdapter.address().port}/send-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ destination: 'Grupo Teste', message: 'Oferta', idempotency_key: 'offer:server:2' }),
    });
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: 'Falha ao enfileirar oferta no roteador' });
    assert.equal(calls.length, evolutionCallsBefore);
  } finally {
    await close(routerAdapter);
    await close(failingRouter);
  }
});

test('provider router exige idempotency_key e não chama nenhum transporte', async () => {
  const routerConfig = createRouterConfig('observer_buffer_router_key.json');
  const routerAdapter = createApp({ config: routerConfig });
  await listen(routerAdapter, '127.0.0.1', 0);
  try {
    const evolutionCallsBefore = calls.length;
    const routerCallsBefore = routerCalls.length;
    const response = await fetch(`http://127.0.0.1:${routerAdapter.address().port}/send-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ destination: 'Grupo Teste', message: 'Oferta' }),
    });
    assert.equal(response.status, 400);
    assert.match((await response.json()).error, /idempotency_key/);
    assert.equal(calls.length, evolutionCallsBefore);
    assert.equal(routerCalls.length, routerCallsBefore);
  } finally {
    await close(routerAdapter);
  }
});

test('observer collect permanece inalterado com provider router', async () => {
  const routerConfig = createRouterConfig('observer_buffer_router_collect.json');
  routerConfig.observerEnabled = true;
  routerConfig.observerGroupJids = ['group-fixture@g.us'];
  const routerAdapter = createApp({ config: routerConfig });
  await listen(routerAdapter, '127.0.0.1', 0);
  try {
    const routerCallsBefore = routerCalls.length;
    const response = await fetch(`http://127.0.0.1:${routerAdapter.address().port}/observer/collect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { enabled: true, messages: [] });
    assert.equal(routerCalls.length, routerCallsBefore);
  } finally {
    await close(routerAdapter);
  }
});

test('POST /send-message rejeita destino observer sem chamar a Evolution', async () => {
  const observerConfig = getConfig({
    EVOLUTION_BASE_URL: fakeEvolutionUrl,
    EVOLUTION_API_KEY: 'test-key',
    EVOLUTION_INSTANCIA_ENVIO: 'descontos_envio',
    EVOLUTION_INSTANCIA_OBSERVER: 'descontos_observer',
    EVOLUTION_GROUP_MAP_JSON: JSON.stringify({ 'Agenda': { jid: '120363000000002@g.us', sender_instance: 'observer' } }),
    EVOLUTION_OBSERVER_BUFFER_PATH: path.join(tmp, 'observer_buffer_send.json'),
  });
  const observerAdapter = createApp({ config: observerConfig });
  await listen(observerAdapter, '127.0.0.1', 0);
  try {
    const callsBeforeRequest = calls.length;
    const response = await fetch(`http://127.0.0.1:${observerAdapter.address().port}/send-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ destination: 'Agenda', message: 'Agenda do dia' }),
    });
    assert.equal(response.status, 403);
    assert.match((await response.json()).error, /descontos_observer.*somente leitura.*descontos_envio/);
    assert.equal(calls.length, callsBeforeRequest);
  } finally {
    await close(observerAdapter);
  }
});

test('POST /send-message com destino ausente retorna erro sem derrubar o adapter', async () => {
  const response = await post('/send-message', { destination: 'Grupo Ausente', message: 'Oferta' });
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /não encontrado no mapa Evolution/);
  assert.equal((await fetch(`${adapterUrl}/health`)).status, 200);
});

test('POST /send-message com image_url chama sendMedia', async () => {
  const response = await post('/send-message', {
    destination: '120363000000001@g.us',
    message: 'Oferta imagem',
    image_url: 'https://example.com/foto.png',
  });
  assert.equal(response.status, 200);
  const call = calls.at(-1);
  assert.equal(call.url, '/message/sendMedia/descontos_envio');
  assert.equal(call.body.number, '120363000000001@g.us');
  assert.equal(call.body.caption, 'Oferta imagem');
  assert.equal(call.body.media, 'https://example.com/foto.png');
  assert.equal(call.body.mimetype, 'image/png');
});

test('POST /send-message converte image_url sem extensão para base64', async () => {
  const response = await post('/send-message', {
    destination: '120363000000001@g.us',
    message: 'Oferta imagem sem extensão',
    image_url: `${fakeEvolutionUrl}/image-no-extension`,
  });
  assert.equal(response.status, 200);
  const call = calls.at(-1);
  assert.equal(call.url, '/message/sendMedia/descontos_envio');
  assert.equal(call.body.number, '120363000000001@g.us');
  assert.equal(call.body.caption, 'Oferta imagem sem extensão');
  assert.equal(call.body.media, Buffer.from('fake-jpeg-bytes').toString('base64'));
  assert.equal(call.body.mimetype, 'image/jpeg');
  assert.equal(call.body.fileName, 'offer.jpg');
});

test('POST /send não aceita text_path legado no fluxo Evolution', async () => {
  const response = await post('/send', {
    target: 'Grupo Teste',
    items: [{ id: '1', text_path: '/tmp/legado.txt', image_url: 'https://example.com/foto.jpg' }],
  });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.sent, 0);
  assert.equal(body.errors, 1);
  assert.match(body.failures[0].reason, /text\/message\/caption/);
});

test('webhook normaliza, deduplica e collect preserva schema observer', async () => {
  const payload = {
    event: 'messages.upsert',
    instance: 'descontos_observer',
    data: {
      key: {
        remoteJid: '120363000000001@g.us',
        id: 'MSG1',
        participant: '5511999999999@s.whatsapp.net',
      },
      messageTimestamp: Math.floor(Date.now() / 1000),
      message: {
        extendedTextMessage: { text: 'Oferta https://example.com/produto' },
      },
    },
  };

  assert.equal((await post('/webhook/whatsapp', payload)).status, 200);
  assert.equal((await post('/webhook/whatsapp', payload)).status, 200);

  const response = await post('/observer/collect', {});
  const body = await response.json();
  assert.equal(body.enabled, true);
  const messages = body.messages.filter((message) => message.message_id === 'MSG1');
  assert.equal(messages.length, 1);
  assert.equal(messages[0].group_subject, 'Grupo Teste');
  assert.equal(messages[0].raw_type, 'extendedTextMessage');
  assert.deepEqual(messages[0].urls, ['https://example.com/produto']);
  for (const key of [
    'message_id', 'group_jid', 'group_subject', 'sender_hash', 'sent_at', 'text', 'has_image', 'urls', 'raw_type',
    'collected_at', 'reacoes', 'visualizacoes', 'encaminhamentos', 'comentarios', 'repostado', 'qtd_repostagens', 'fixado',
  ]) {
    assert.ok(Object.hasOwn(messages[0], key), `campo ausente: ${key}`);
  }
});

test('webhook ignora eventos e instâncias fora do escopo observer', async () => {
  const base = {
    data: {
      key: { remoteJid: '120363000000001@g.us', id: 'IGNORADO', participant: '5511999999999@s.whatsapp.net' },
      messageTimestamp: Math.floor(Date.now() / 1000),
      message: { conversation: 'não deve entrar' },
    },
  };
  assert.deepEqual(await (await post('/webhook/whatsapp', { ...base, event: 'SEND_MESSAGE', instance: 'descontos_observer' })).json(), { accepted: true, recorded: 0 });
  assert.deepEqual(await (await post('/webhook/whatsapp', { ...base, event: 'messages.upsert', instance: 'outra_instancia' })).json(), { accepted: true, recorded: 0 });
  const body = await (await post('/observer/collect', {})).json();
  assert.equal(body.messages.some((message) => message.message_id === 'IGNORADO'), false);
});

test('GET /observer/groups retorna interseção entre allowlist e mapa', async () => {
  const response = await fetch(`${adapterUrl}/observer/groups`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    enabled: true,
    groups: [{ jid: '120363000000001@g.us', subject: 'Grupo Teste' }],
  });
});

test('GET /observer/groups retorna lista vazia quando observer está desabilitado', async () => {
  const disabledConfig = getConfig({
    EVOLUTION_BASE_URL: fakeEvolutionUrl,
    EVOLUTION_API_KEY: 'test-key',
    EVOLUTION_GROUP_MAP_JSON: JSON.stringify({ 'Grupo Teste': { jid: '120363000000001@g.us', subject: 'Grupo Teste' } }),
    WA_OBSERVER_ENABLED: 'false',
    WA_OBSERVER_GROUP_JIDS: '120363000000001@g.us',
  });
  const disabledAdapter = createApp({ config: disabledConfig });
  await listen(disabledAdapter, '127.0.0.1', 0);
  try {
    const response = await fetch(`http://127.0.0.1:${disabledAdapter.address().port}/observer/groups`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { enabled: false, groups: [] });
  } finally {
    await close(disabledAdapter);
  }
});

function createRouterConfig(bufferName, routerBaseUrl = fakeRouterUrl) {
  return getConfig({
    EVOLUTION_BASE_URL: fakeEvolutionUrl,
    EVOLUTION_API_KEY: 'test-key',
    EVOLUTION_GROUP_MAP_JSON: JSON.stringify({
      'Grupo Teste': { jid: 'group-fixture@g.us', subject: 'Grupo Teste', router_alias: 'group-fixture' },
    }),
    EVOLUTION_OBSERVER_BUFFER_PATH: path.join(tmp, bufferName),
    WA_OUTBOUND_PROVIDER: 'router',
    WA_ROUTER_BASE_URL: routerBaseUrl,
    WA_ROUTER_TOKEN: 'router-token',
  });
}

async function post(pathname, body) {
  return fetch(`${adapterUrl}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function listen(server, host, port) {
  return new Promise((resolve) => server.listen(port, host, resolve));
}

function close(server) {
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}
