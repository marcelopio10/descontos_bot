import './env.js';
import http from 'node:http';
import { getConfig } from './config.js';
import { getConnectionStatus, sendMedia, sendText } from './evolutionClient.js';
import { loadGroupMap } from './groupMap.js';
import { extractWebhookMessages, ObserverBuffer } from './observerBuffer.js';

export function createApp({ config = getConfig(), groupMap = loadGroupMap(config), observer = new ObserverBuffer(config, groupMap) } = {}) {
  async function route(req, res) {
    try {
      const url = new URL(req.url || '/', 'http://127.0.0.1');
      if (req.method === 'GET' && url.pathname === '/health') {
        return json(res, 200, { ok: true, service: 'evolution_adapter' });
      }
      if (req.method === 'GET' && url.pathname === '/status') {
        return json(res, 200, await getConnectionStatus(config));
      }
      if (req.method === 'POST' && url.pathname === '/send-message') {
        await handleSendMessage(req, res, config, groupMap);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/send') {
        await handleSendBatch(req, res, config, groupMap);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/webhook/whatsapp') {
        await handleWebhook(req, res, observer);
        return;
      }
      if (req.method === 'POST' && url.pathname === '/observer/collect') {
        await readJson(req).catch(() => ({}));
        return json(res, 200, observer.collect());
      }
      if (req.method === 'GET' && url.pathname === '/observer/groups') {
        const groups = config.observerEnabled ? groupMap.listAllowed(config.observerGroupJids) : [];
        return json(res, 200, { enabled: config.observerEnabled, groups });
      }
      return json(res, 404, { error: 'not found' });
    } catch (error) {
      const status = error instanceof ObserverReadOnlyError ? 403 : 500;
      return json(res, status, { error: error instanceof Error ? error.message : String(error) });
    }
  }

  return http.createServer(route);
}

async function handleSendMessage(req, res, config, groupMap) {
  const body = await readJson(req);
  const { destination, message, image_url } = body;
  if (!destination || typeof destination !== 'string') return json(res, 400, { error: "Campo 'destination' é obrigatório (string)" });
  if (!message || typeof message !== 'string') return json(res, 400, { error: "Campo 'message' é obrigatório (string)" });
  if (image_url !== undefined && typeof image_url !== 'string') return json(res, 400, { error: "Campo 'image_url' deve ser string quando informado" });

  const target = groupMap.resolveTarget(destination);
  const senderConfig = await configForTarget(config, target);
  const result = image_url
    ? await sendMedia(senderConfig, target.jid, message, image_url)
    : await sendText(senderConfig, target.jid, message);
  return json(res, 200, result);
}

async function handleSendBatch(req, res, config, groupMap) {
  const body = await readJson(req);
  const { target, items } = body;
  if (!target || typeof target !== 'string') return json(res, 400, { error: "Campo 'target' é obrigatório (string)" });
  if (!Array.isArray(items) || items.length === 0) return json(res, 400, { error: "Campo 'items' deve ser array não-vazio" });

  const resolvedTarget = groupMap.resolveTarget(target);
  const senderConfig = await configForTarget(config, resolvedTarget);
  const result = { sent: 0, errors: 0, failures: [] };
  for (const item of items) {
    try {
      const caption = resolveItemText(item);
      const mediaUrl = item.image_url || item.media_url;
      if (!mediaUrl) throw new Error('item sem image_url/media_url para Evolution');
      await sendMedia(senderConfig, resolvedTarget.jid, caption, mediaUrl);
      result.sent += 1;
    } catch (error) {
      result.errors += 1;
      result.failures.push({ id: String(item?.id || ''), reason: error instanceof Error ? error.message : String(error) });
    }
  }
  return json(res, 200, result);
}

async function configForTarget(config, target) {
  if (target.senderInstance !== 'observer') return config;
  throw new ObserverReadOnlyError();
}

class ObserverReadOnlyError extends Error {
  constructor() {
    super('A instância descontos_observer é somente leitura; migre o destino para descontos_envio');
    this.name = 'ObserverReadOnlyError';
  }
}

function resolveItemText(item) {
  if (typeof item?.text === 'string') return item.text;
  if (typeof item?.message === 'string') return item.message;
  if (typeof item?.caption === 'string') return item.caption;
  throw new Error('item sem text/message/caption');
}

async function handleWebhook(req, res, observer) {
  const body = await readJson(req);
  if (!isMessagesUpsertEvent(body) || !isObserverInstance(body, observer.config.instanciaObserver)) {
    return json(res, 200, { accepted: true, recorded: 0 });
  }
  const messages = extractWebhookMessages(body);
  let recorded = 0;
  for (const message of messages) {
    if (observer.record(message)) recorded += 1;
  }
  return json(res, 200, { accepted: true, recorded });
}

function isMessagesUpsertEvent(body) {
  const event = body?.event;
  return !event || event === 'messages.upsert' || event === 'MESSAGES_UPSERT';
}

function isObserverInstance(body, expectedInstance) {
  const instance = body?.instance || body?.instanceName || body?.data?.instance || body?.data?.instanceName;
  return !instance || instance === expectedInstance;
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf-8');
  if (!raw) return {};
  return JSON.parse(raw);
}

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const config = getConfig();
  const server = createApp({ config });
  server.listen(config.port, config.host, () => {
    console.log(`[evolution_adapter] rodando em http://${config.host}:${config.port}`);
  });
}
