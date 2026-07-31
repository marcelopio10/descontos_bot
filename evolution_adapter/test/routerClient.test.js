import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, beforeEach, test } from 'node:test';

import { enqueueOffer, RouterRequestError } from '../src/routerClient.js';

let fakeRouter;
let fakeRouterUrl;
const calls = [];

before(async () => {
  fakeRouter = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const rawBody = Buffer.concat(chunks).toString('utf-8');
    calls.push({
      method: req.method,
      url: req.url,
      headers: req.headers,
      body: rawBody ? JSON.parse(rawBody) : null,
    });
    res.writeHead(202, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ queued: true, id: 'queue-1', priority: 3 }));
  });
  await listen(fakeRouter, '127.0.0.1', 0);
  fakeRouterUrl = `http://127.0.0.1:${fakeRouter.address().port}`;
});

beforeEach(() => calls.splice(0));

after(async () => close(fakeRouter));

test('enqueueOffer envia oferta resolvida pelo mapa com texto, mídia e idempotency key', async () => {
  const groupMap = mappedGroupMap();
  const result = await enqueueOffer(
    { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
    groupMap,
    'group-display-fixture',
    {
      idempotencyKey: 'offer:42:group:test',
      text: 'Oferta de teste',
      mediaUrl: 'https://example.com/oferta.jpg',
    },
  );

  assert.deepEqual(result, { queued: true, id: 'queue-1', priority: 3 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].url, '/v1/outbound');
  assert.equal(calls[0].headers.authorization, 'Bearer router-test-token');
  assert.deepEqual(calls[0].body, {
    type: 'offer',
    destination: 'group-fixture',
    idempotency_key: 'offer:42:group:test',
    text: 'Oferta de teste',
    media_url: 'https://example.com/oferta.jpg',
  });
});

test('enqueueOffer exige idempotency key', async () => {
  await assert.rejects(
    enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      mappedGroupMap(),
      'group-fixture',
      { text: 'Oferta' },
    ),
    /idempotency key/i,
  );
  assert.equal(calls.length, 0);
});

test('enqueueOffer exige router_alias opaco no alvo mapeado', async () => {
  const groupMap = mappedGroupMap();
  groupMap.resolveTarget = () => ({ jid: 'group-fixture@g.us', subject: 'group-display-fixture' });
  await assert.rejects(
    enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      groupMap,
      'group-display-fixture',
      { idempotencyKey: 'offer:missing-router-alias', text: 'Oferta' },
    ),
    /router_alias/,
  );
  assert.equal(calls.length, 0);
});

test('enqueueOffer rejeita JID arbitrário que não pertence ao mapa local', async () => {
  await assert.rejects(
    enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      mappedGroupMap(),
      'attacker-fixture@g.us',
      { idempotencyKey: 'offer:43', text: 'Oferta' },
    ),
    /alias simbólico/,
  );
  assert.equal(calls.length, 0);
});

test('enqueueOffer exige alias simbólico mesmo para JID presente no mapa', async () => {
  await assert.rejects(
    enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      mappedGroupMap(),
      'group-fixture@g.us',
      { idempotencyKey: 'offer:mapped-jid', text: 'Oferta' },
    ),
    /alias simbólico/,
  );
  assert.equal(calls.length, 0);
});

test('enqueueOffer não registra JID, texto ou token em logs', async () => {
  const logs = [];
  const originalLog = console.log;
  const originalError = console.error;
  console.log = (...args) => logs.push(args.join(' '));
  console.error = (...args) => logs.push(args.join(' '));
  try {
    await enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      mappedGroupMap(),
      'group-fixture',
      { idempotencyKey: 'offer:logs', text: 'Oferta sigilosa' },
    );
  } finally {
    console.log = originalLog;
    console.error = originalError;
  }
  assert.deepEqual(logs, []);
});

test('enqueueOffer sanitiza falha HTTP sem expor resposta do roteador', async () => {
  fakeRouter.removeAllListeners('request');
  fakeRouter.on('request', async (req, res) => {
    for await (const _chunk of req) {
      // Drena a requisição sem registrar conteúdo sensível.
    }
    res.writeHead(503, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'token=segredo jid=group-fixture@g.us' }));
  });

  await assert.rejects(
    enqueueOffer(
      { routerBaseUrl: fakeRouterUrl, routerToken: 'router-test-token' },
      mappedGroupMap(),
      'group-fixture',
      { idempotencyKey: 'offer:44', text: 'Oferta secreta' },
    ),
    (error) => {
      assert.ok(error instanceof RouterRequestError);
      assert.equal(error.message, 'Falha ao enfileirar oferta no roteador');
      assert.equal(error.statusCode, 502);
      assert.doesNotMatch(String(error), /segredo|120363|Oferta secreta|router-test-token/);
      return true;
    },
  );
});

function mappedGroupMap() {
  const target = {
    jid: 'group-fixture@g.us',
    subject: 'group-display-fixture',
    senderInstance: 'envio',
    router_alias: 'group-fixture',
  };
  return {
    resolveTarget(destination) {
      if (destination === 'group-fixture' || destination === 'group-display-fixture' || destination === target.jid) return target;
      if (destination.endsWith('@g.us')) return { jid: destination, subject: destination, senderInstance: 'envio' };
      throw new Error('não encontrado');
    },
    listAllowed(jids) {
      return jids.includes(target.jid) ? [{ jid: target.jid, subject: target.subject }] : [];
    },
  };
}

function listen(server, host, port) {
  return new Promise((resolve) => server.listen(port, host, resolve));
}

function close(server) {
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}
