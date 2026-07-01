import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const URL_REGEX = /https?:\/\/[^\s)\]}>"]+/gi;

export class ObserverBuffer {
  constructor(config, groupMap) {
    this.config = config;
    this.groupMap = groupMap;
    this.messages = [];
    this.load();
  }

  load() {
    try {
      if (existsSync(this.config.observerBufferPath)) {
        const parsed = JSON.parse(readFileSync(this.config.observerBufferPath, 'utf-8'));
        if (Array.isArray(parsed)) this.messages = parsed;
      }
    } catch (error) {
      console.error(`[evolution_adapter] erro ao carregar buffer: ${error.message}`);
    }
  }

  save() {
    const dir = path.dirname(this.config.observerBufferPath);
    mkdirSync(dir, { recursive: true });
    writeFileSync(this.config.observerBufferPath, JSON.stringify(this.messages, null, 2), 'utf-8');
  }

  record(raw) {
    if (!this.config.observerEnabled || this.config.observerGroupJids.length === 0) return null;
    const normalized = normalizeIncomingMessage(raw, this.groupMap, this.config);
    if (!normalized || !this.config.observerGroupJids.includes(normalized.group_jid)) return null;
    const duplicate = this.messages.some((item) => item.message_id === normalized.message_id);
    if (!duplicate) {
      this.messages.push(normalized);
      this.trim();
      this.save();
    }
    return normalized;
  }

  collect() {
    if (!this.config.observerEnabled || this.config.observerGroupJids.length === 0) {
      return { enabled: this.config.observerEnabled, messages: [] };
    }
    const cutoff = Date.now() - this.config.observerLookbackHours * 60 * 60 * 1000;
    const allowed = new Set(this.config.observerGroupJids);
    const perGroupCount = new Map();
    const messages = [...this.messages]
      .filter((message) => allowed.has(message.group_jid))
      .filter((message) => Date.parse(message.sent_at) >= cutoff)
      .sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at))
      .filter((message) => {
        const count = perGroupCount.get(message.group_jid) ?? 0;
        if (count >= this.config.observerMaxMessagesPerGroup) return false;
        perGroupCount.set(message.group_jid, count + 1);
        return true;
      });
    return { enabled: true, messages };
  }

  trim() {
    const cutoff = Date.now() - this.config.observerLookbackHours * 60 * 60 * 1000;
    const allowed = new Set(this.config.observerGroupJids);
    const perGroupCount = new Map();
    this.messages = this.messages
      .filter((message) => allowed.has(message.group_jid))
      .filter((message) => Date.parse(message.sent_at) >= cutoff)
      .sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
      .filter((message) => {
        const count = perGroupCount.get(message.group_jid) ?? 0;
        if (count >= this.config.observerMaxMessagesPerGroup) return false;
        perGroupCount.set(message.group_jid, count + 1);
        return true;
      });
  }
}

export function normalizeIncomingMessage(raw, groupMap, config) {
  const key = raw?.key ?? {};
  const groupJid = String(key.remoteJid ?? raw?.remoteJid ?? '');
  const messageId = String(key.id ?? raw?.id ?? raw?.messageId ?? '');
  if (!groupJid.endsWith('@g.us') || !messageId) return null;

  const body = raw?.message ?? raw?.data?.message ?? {};
  const rawType = getRawType(body);
  const text = extractText(body).trim();
  if (!text) return null;

  const sender = String(key.participant ?? key.participantPn ?? raw?.participant ?? raw?.sender ?? groupJid);
  const sentAt = parseTimestamp(raw?.messageTimestamp ?? raw?.timestamp ?? raw?.dateTime);
  return {
    message_id: messageId,
    group_jid: groupJid,
    group_subject: groupMap.subjectFor(groupJid),
    sender_hash: hashSender(sender, config.senderHashSalt),
    sent_at: sentAt.toISOString(),
    text,
    has_image: rawType === 'imageMessage' || Boolean(body?.imageMessage),
    urls: extractUrls(text),
    raw_type: rawType,
    collected_at: new Date().toISOString(),
    reacoes: null,
    visualizacoes: null,
    encaminhamentos: null,
    comentarios: null,
    repostado: null,
    qtd_repostagens: null,
    fixado: null,
  };
}

export function extractWebhookMessages(payload) {
  const candidates = [];
  if (Array.isArray(payload?.data?.messages)) candidates.push(...payload.data.messages);
  if (Array.isArray(payload?.messages)) candidates.push(...payload.messages);
  if (payload?.data && !Array.isArray(payload.data)) candidates.push(payload.data);
  if (payload?.message) candidates.push(payload.message);
  if (payload?.key && payload?.message) candidates.push(payload);
  return candidates.filter((item) => item && typeof item === 'object');
}

function getRawType(body) {
  return Object.keys(body || {})[0] ?? 'unknown';
}

function extractText(body) {
  return [
    body?.conversation,
    body?.extendedTextMessage?.text,
    body?.imageMessage?.caption,
    body?.videoMessage?.caption,
    body?.documentMessage?.caption,
  ]
    .filter((value) => typeof value === 'string' && value.trim())
    .join('\n');
}

function extractUrls(text) {
  return Array.from(new Set(text.match(URL_REGEX) ?? []));
}

function hashSender(sender, salt) {
  return createHash('sha256').update(`${salt}:${sender}`).digest('hex');
}

function parseTimestamp(value) {
  if (typeof value === 'number') return new Date(value > 10_000_000_000 ? value : value * 1000);
  if (typeof value === 'string') {
    const numeric = Number.parseInt(value, 10);
    if (Number.isFinite(numeric)) return new Date(numeric > 10_000_000_000 ? numeric : numeric * 1000);
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return new Date(parsed);
  }
  return new Date();
}
