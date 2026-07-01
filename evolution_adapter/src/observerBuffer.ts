import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { getConfig } from "./config.js";

export interface ObservedMessage {
  message_id: string;
  group_jid: string;
  group_subject: string;
  sender_hash: string;
  sent_at: string;
  text: string;
  has_image: boolean;
  urls: string[];
  raw_type: string;
  collected_at: string;
  reacoes: number | null;
  visualizacoes: number | null;
  encaminhamentos: number | null;
  comentarios: number | null;
  repostado: boolean | null;
  qtd_repostagens: number | null;
  fixado: boolean | null;
}

interface ObserverConfig {
  enabled: boolean;
  groupJids: string[];
  lookbackHours: number;
  maxMessagesPerGroup: number;
  senderHashSalt: string;
}

let buffer: ObservedMessage[] = [];
let loaded = false;

export function collectObservedMessages(): { enabled: boolean; messages: ObservedMessage[] } {
  ensureBufferLoaded();
  const config = getObserverConfig();
  if (!config.enabled || config.groupJids.length === 0) return { enabled: config.enabled, messages: [] };

  const cutoff = Date.now() - config.lookbackHours * 60 * 60 * 1000;
  const allowed = new Set(config.groupJids);
  const perGroupCount = new Map<string, number>();
  const messages = [...buffer]
    .filter((message) => allowed.has(message.group_jid))
    .filter((message) => Date.parse(message.sent_at) >= cutoff)
    .sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at))
    .filter((message) => {
      const count = perGroupCount.get(message.group_jid) ?? 0;
      if (count >= config.maxMessagesPerGroup) return false;
      perGroupCount.set(message.group_jid, count + 1);
      return true;
    });

  return { enabled: true, messages };
}

export function listObserverGroups(): { enabled: boolean; groups: Array<{ jid: string; subject: string }> } {
  const observerConfig = getObserverConfig();
  const subjectsByJid = reverseGroupMap(getConfig().groupMapJson);
  const groups = observerConfig.groupJids.map((jid) => ({
    jid,
    subject: subjectsByJid.get(jid) || jid,
  }));
  return { enabled: observerConfig.enabled, groups: observerConfig.enabled ? groups : [] };
}

export function storeWebhookPayload(
  payload: Record<string, any>,
  observerInstance: string
): { stored: number; duplicate: number; ignored: number } {
  ensureBufferLoaded();
  const observerConfig = getObserverConfig();
  const groupMapJson = getConfig().groupMapJson;

  if (!observerConfig.enabled || observerConfig.groupJids.length === 0) return { stored: 0, duplicate: 0, ignored: 1 };
  if (payload?.instance !== observerInstance) return { stored: 0, duplicate: 0, ignored: 1 };
  if (!isMessagesUpsertEvent(payload?.event)) return { stored: 0, duplicate: 0, ignored: 1 };

  const rows = extractRawMessages(payload);
  let stored = 0;
  let duplicate = 0;
  let ignored = 0;
  for (const raw of rows) {
    const normalized = normalizeEvolutionMessage(raw, observerConfig, groupMapJson);
    if (!normalized) {
      ignored++;
      continue;
    }
    const exists = buffer.some((item) => item.group_jid === normalized.group_jid && item.message_id === normalized.message_id);
    if (exists) {
      duplicate++;
      continue;
    }
    buffer.push(normalized);
    trimBuffer(observerConfig);
    stored++;
  }
  if (stored > 0) saveBuffer();
  return { stored, duplicate, ignored };
}

export function resetObserverBufferForTests(): void {
  buffer = [];
  loaded = true;
}

function extractRawMessages(payload: Record<string, any>): Record<string, any>[] {
  const data = payload?.data;
  if (Array.isArray(data?.messages)) return data.messages;
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") return [data];
  return [];
}

function normalizeEvolutionMessage(
  raw: Record<string, any>,
  config: ObserverConfig,
  groupMapJson: string
): ObservedMessage | null {
  const key = raw?.key || {};
  const groupJid = String(key.remoteJid || raw?.remoteJid || "");
  const messageId = String(key.id || raw?.id || "");
  if (!groupJid.endsWith("@g.us") || !messageId) return null;

  const allowed = new Set(config.groupJids);
  if (!allowed.has(groupJid)) return null;

  const message = raw?.message || {};
  const text = extractText(message, raw).trim();
  if (!text) return null;

  return {
    message_id: messageId,
    group_jid: groupJid,
    group_subject: reverseGroupMap(groupMapJson).get(groupJid) || groupJid,
    sender_hash: hashSender(String(key.participant || key.participantPn || raw?.participant || "unknown"), config.senderHashSalt),
    sent_at: parseTimestamp(raw?.messageTimestamp || raw?.timestamp).toISOString(),
    text,
    has_image: Boolean(message?.imageMessage),
    urls: Array.from(new Set(text.match(/https?:\/\/[^\s)\]}>\"]+/gi) || [])),
    raw_type: primaryMessageType(message),
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

function extractText(message: Record<string, any>, raw: Record<string, any>): string {
  return [
    message.conversation,
    message.extendedTextMessage?.text,
    message.imageMessage?.caption,
    message.videoMessage?.caption,
    message.documentMessage?.caption,
    raw?.text,
  ]
    .filter((value) => typeof value === "string" && value.trim())
    .join("\n");
}

function primaryMessageType(message: Record<string, any>): string {
  const ignored = new Set(["messageContextInfo", "senderKeyDistributionMessage"]);
  return Object.keys(message).find((key) => !ignored.has(key)) || Object.keys(message)[0] || "unknown";
}

function isMessagesUpsertEvent(event: unknown): boolean {
  const normalized = String(event || "").trim().toLowerCase().replace(/_/g, ".");
  return normalized === "messages.upsert";
}

function getObserverConfig(): ObserverConfig {
  return {
    enabled: process.env.WA_OBSERVER_ENABLED?.trim().toLowerCase() === "true",
    groupJids: Array.from(
      new Set(
        (process.env.WA_OBSERVER_GROUP_JIDS || "")
          .split(",")
          .map((jid) => jid.trim())
          .filter((jid) => jid.endsWith("@g.us"))
      )
    ),
    lookbackHours: parsePositiveInt(process.env.WA_OBSERVER_LOOKBACK_HOURS, 24),
    maxMessagesPerGroup: parsePositiveInt(process.env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP, 300),
    senderHashSalt: process.env.WA_OBSERVER_SENDER_HASH_SALT || "descontos-bot-observer",
  };
}

function reverseGroupMap(groupMapJson: string): Map<string, string> {
  const reversed = new Map<string, string>();
  try {
    const parsed = JSON.parse(groupMapJson || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      for (const [subject, jid] of Object.entries(parsed)) {
        if (typeof subject === "string" && typeof jid === "string" && jid.endsWith("@g.us")) {
          reversed.set(jid, subject);
        }
      }
    }
  } catch {
    return reversed;
  }
  return reversed;
}

function parseTimestamp(value: unknown): Date {
  if (typeof value === "number") return new Date(value * 1000);
  if (typeof value === "string" && /^\d+$/.test(value)) return new Date(Number.parseInt(value, 10) * 1000);
  return new Date();
}

function hashSender(sender: string, salt: string): string {
  return createHash("sha256").update(`${salt}:${sender}`).digest("hex");
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const value = Number.parseInt(String(raw ?? ""), 10);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function bufferPath(): string {
  const envPath = process.env.WA_OBSERVER_BUFFER_PATH?.trim();
  if (envPath) return envPath;
  return resolve(process.cwd(), "runtime", "evolution_observer_buffer.json");
}

function ensureBufferLoaded(): void {
  if (loaded) return;
  loaded = true;
  const filePath = bufferPath();
  try {
    if (!existsSync(filePath)) return;
    const parsed = JSON.parse(readFileSync(filePath, "utf8"));
    if (Array.isArray(parsed)) buffer = parsed as ObservedMessage[];
  } catch {
    buffer = [];
  }
}

function saveBuffer(): void {
  const filePath = bufferPath();
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(buffer, null, 2), "utf8");
}

function trimBuffer(config: ObserverConfig): void {
  const cutoff = Date.now() - config.lookbackHours * 60 * 60 * 1000;
  const limit = Math.max(config.maxMessagesPerGroup, config.groupJids.length * config.maxMessagesPerGroup);
  buffer = buffer
    .filter((message) => Date.parse(message.sent_at) >= cutoff)
    .sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at))
    .slice(-limit);
}
