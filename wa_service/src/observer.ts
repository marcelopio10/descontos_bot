import { createHash } from "crypto";

export interface ObserverConfig {
  enabled: boolean;
  groupJids: string[];
  lookbackHours: number;
  maxMessagesPerGroup: number;
  senderHashSalt: string;
}

export interface ObserverGroup {
  jid: string;
  subject: string;
}

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
}

const DEFAULT_LOOKBACK_HOURS = 24;
const DEFAULT_MAX_MESSAGES_PER_GROUP = 300;
const DEFAULT_SENDER_HASH_SALT = "descontos-bot-observer";
const URL_REGEX = /https?:\/\/[^\s)\]}>"]+/gi;

let observedBuffer: ObservedMessage[] = [];

export function getObserverConfig(): ObserverConfig {
  return {
    enabled: process.env.WA_OBSERVER_ENABLED?.trim().toLowerCase() === "true",
    groupJids: parseGroupJids(process.env.WA_OBSERVER_GROUP_JIDS ?? ""),
    lookbackHours: parsePositiveInt(process.env.WA_OBSERVER_LOOKBACK_HOURS, DEFAULT_LOOKBACK_HOURS),
    maxMessagesPerGroup: parsePositiveInt(
      process.env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP,
      DEFAULT_MAX_MESSAGES_PER_GROUP
    ),
    senderHashSalt: process.env.WA_OBSERVER_SENDER_HASH_SALT?.trim() || DEFAULT_SENDER_HASH_SALT,
  };
}

export function listObserverGroups(
  allGroups: ObserverGroup[],
  config: ObserverConfig = getObserverConfig()
): { enabled: boolean; groups: ObserverGroup[] } {
  if (!config.enabled || config.groupJids.length === 0) {
    return { enabled: config.enabled, groups: [] };
  }
  const allowed = new Set(config.groupJids);
  return {
    enabled: true,
    groups: allGroups.filter((group) => allowed.has(group.jid)),
  };
}

export function normalizeIncomingMessage(
  raw: Record<string, any>,
  groupSubject?: string,
  config: ObserverConfig = getObserverConfig()
): ObservedMessage | null {
  const key = raw?.key ?? {};
  const groupJid = String(key.remoteJid ?? "");
  const messageId = String(key.id ?? "");
  if (!groupJid.endsWith("@g.us") || !messageId) return null;

  const body = raw?.message ?? {};
  const rawType = getRawType(body);
  const text = extractText(body).trim();
  if (!text) return null;

  const sentAt = parseTimestamp(raw?.messageTimestamp);
  const sender = String(key.participant ?? key.participantPn ?? key.remoteJid ?? "unknown");
  return {
    message_id: messageId,
    group_jid: groupJid,
    group_subject: groupSubject || groupJid,
    sender_hash: hashSender(sender, config.senderHashSalt),
    sent_at: sentAt.toISOString(),
    text,
    has_image: rawType === "imageMessage" || Boolean(body?.imageMessage),
    urls: extractUrls(text),
    raw_type: rawType,
    collected_at: new Date().toISOString(),
  };
}

export function recordObservedMessage(
  raw: Record<string, any>,
  groupSubject?: string,
  config: ObserverConfig = getObserverConfig()
): ObservedMessage | null {
  if (!config.enabled || config.groupJids.length === 0) return null;
  const message = normalizeIncomingMessage(raw, groupSubject, config);
  if (!message || !config.groupJids.includes(message.group_jid)) return null;

  const duplicate = observedBuffer.some(
    (item) => item.group_jid === message.group_jid && item.message_id === message.message_id
  );
  if (!duplicate) {
    observedBuffer.push(message);
    trimBuffer(config);
  }
  return message;
}

export function collectObservedMessages(
  config: ObserverConfig = getObserverConfig()
): { enabled: boolean; messages: ObservedMessage[] } {
  if (!config.enabled || config.groupJids.length === 0) {
    return { enabled: config.enabled, messages: [] };
  }
  const cutoff = Date.now() - config.lookbackHours * 60 * 60 * 1000;
  const allowed = new Set(config.groupJids);
  const perGroupCount = new Map<string, number>();
  const messages = [...observedBuffer]
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

export function resetObserverBufferForTests() {
  observedBuffer = [];
}

function parseGroupJids(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(",")
        .map((value) => value.trim())
        .filter((value) => value.endsWith("@g.us"))
    )
  );
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  const value = Number.parseInt(String(raw ?? ""), 10);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function hashSender(sender: string, salt: string): string {
  return createHash("sha256").update(`${salt}:${sender}`).digest("hex");
}

function parseTimestamp(value: unknown): Date {
  if (typeof value === "number") return new Date(value * 1000);
  if (typeof value === "string") return new Date(Number.parseInt(value, 10) * 1000);
  if (value && typeof value === "object" && "toNumber" in value && typeof value.toNumber === "function") {
    return new Date(value.toNumber() * 1000);
  }
  return new Date();
}

function getRawType(body: Record<string, any>): string {
  return Object.keys(body)[0] ?? "unknown";
}

function extractText(body: Record<string, any>): string {
  return [
    body.conversation,
    body.extendedTextMessage?.text,
    body.imageMessage?.caption,
    body.videoMessage?.caption,
    body.documentMessage?.caption,
  ]
    .filter((value) => typeof value === "string" && value.trim())
    .join("\n");
}

function extractUrls(text: string): string[] {
  return Array.from(new Set(text.match(URL_REGEX) ?? []));
}

function trimBuffer(config: ObserverConfig) {
  const allowed = new Set(config.groupJids);
  const maxTotal = Math.max(config.maxMessagesPerGroup * Math.max(allowed.size, 1), config.maxMessagesPerGroup);
  observedBuffer = observedBuffer
    .filter((message) => allowed.has(message.group_jid))
    .sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
    .slice(0, maxTotal)
    .sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at));
}
