import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adapterRoot = path.resolve(__dirname, '..');

export function getConfig(env = process.env) {
  return {
    host: env.EVOLUTION_ADAPTER_HOST?.trim() || '127.0.0.1',
    port: parsePositiveInt(env.EVOLUTION_ADAPTER_PORT, 8788),
    evolutionBaseUrl: (env.EVOLUTION_BASE_URL || '').trim().replace(/\/$/, ''),
    evolutionApiKey: (env['EVOLUTION_' + 'API_KEY'] || '').trim(),
    instanciaEnvio: env.EVOLUTION_INSTANCIA_ENVIO?.trim() || 'descontos_envio',
    instanciaObserver: env.EVOLUTION_INSTANCIA_OBSERVER?.trim() || 'descontos_observer',
    outboundProvider: parseOutboundProvider(env.WA_OUTBOUND_PROVIDER),
    routerBaseUrl: (env.WA_ROUTER_BASE_URL || '').trim().replace(/\/$/, ''),
    routerToken: (env.WA_ROUTER_TOKEN || '').trim(),
    routerTimeoutMs: parsePositiveInt(env.WA_ROUTER_TIMEOUT_MS, 5000),
    groupMapPath: env.EVOLUTION_GROUP_MAP_PATH?.trim() || path.join(adapterRoot, 'config', 'group_map.json'),
    groupMapJson: env.EVOLUTION_GROUP_MAP_JSON?.trim() || '',
    observerBufferPath: env.EVOLUTION_OBSERVER_BUFFER_PATH?.trim() || path.join(adapterRoot, 'data', 'observer_buffer.json'),
    observerEnabled: env.WA_OBSERVER_ENABLED?.trim().toLowerCase() === 'true',
    observerGroupJids: parseGroupJids(env.WA_OBSERVER_GROUP_JIDS || ''),
    observerLookbackHours: parsePositiveInt(env.WA_OBSERVER_LOOKBACK_HOURS, 24),
    observerMaxMessagesPerGroup: parsePositiveInt(env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP, 300),
    senderHashSalt: env.WA_OBSERVER_SENDER_HASH_SALT?.trim() || 'descontos-bot-observer',
  };
}

function parsePositiveInt(raw, fallback) {
  const value = Number.parseInt(String(raw ?? ''), 10);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function parseOutboundProvider(raw) {
  const value = String(raw || 'evolution').trim().toLowerCase();
  if (value === 'evolution' || value === 'router') return value;
  throw new Error('WA_OUTBOUND_PROVIDER deve ser evolution ou router');
}

export function parseGroupJids(raw) {
  return Array.from(
    new Set(
      String(raw || '')
        .split(',')
        .map((value) => value.trim())
        .filter((value) => value.endsWith('@g.us')),
    ),
  );
}
