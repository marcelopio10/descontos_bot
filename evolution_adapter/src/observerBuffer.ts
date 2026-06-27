import { createHash } from "node:crypto";

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

const buffer: ObservedMessage[] = [];

export function collectObservedMessages(): { enabled: boolean; messages: ObservedMessage[] } {
  return {
    enabled: isObserverEnabled(),
    messages: [...buffer].sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at)),
  };
}

export function listObserverGroups(): { enabled: boolean; groups: Array<{ jid: string; subject: string }> } {
  const enabled = isObserverEnabled();
  const subjectsByJid = reverseGroupMap();
  const groups = observerGroupJids().map((jid) => ({
    jid,
    subject: subjectsByJid.get(jid) || jid,
  }));
  return { enabled, groups: enabled ? groups : [] };
}

export function storeWebhookPayload(
  payload: Record<string, any>,
  observerInstance: string
): { stored: number; duplicate: number; ignored: number } {
  if (payload?.instance && payload.instance !== observerInstance) return { stored: 0, duplicate: 0, ignored: 1 };
  if (payload?.event && payload.event !== "messages.upsert") return { stored: 0, duplicate: 0, ignored: 1 };

  const rows = extractRawMessages(payload);
  let stored = 0;
  let duplicate = 0;
  let ignored = 0;
  for (const raw of rows) {
    const normalized = normalizeEvolutionMessage(raw);
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
    stored++;
  }
  return { stored, duplicate, ignored };
}

function extractRawMessages(payload: Record<string, any>): Record<string, any>[] {
  const data = payload?.data;
  if (Array.isArray(data?.messages)) return data.messages;
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") return [data];
  return [];
}

function normalizeEvolutionMessage(raw: Record<string, any>): ObservedMessage | null {
  const key = raw?.key || {};
  const groupJid = String(key.remoteJid || raw?.remoteJid || "");
  const messageId = String(key.id || raw?.id || "");
  if (!groupJid.endsWith("@g.us") || !messageId) return null;

  const message = raw?.message || {};
  const text = extractText(message, raw).trim();
  if (!text) return null;

  const allowed = new Set(observerGroupJids());
  if (allowed.size > 0 && !allowed.has(groupJid)) return null;

  return {
    message_id: messageId,
    group_jid: groupJid,
    group_subject: reverseGroupMap().get(groupJid) || groupJid,
    sender_hash: hashSender(String(key.participant || key.participantPn || raw?.participant || "unknown")),
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

function isObserverEnabled(): boolean {
  return process.env.WA_OBSERVER_ENABLED?.trim().toLowerCase() === "true";
}

function observerGroupJids(): string[] {
  return Array.from(
    new Set(
      (process.env.WA_OBSERVER_GROUP_JIDS || "")
        .split(",")
        .map((jid) => jid.trim())
        .filter((jid) => jid.endsWith("@g.us"))
    )
  );
}

function reverseGroupMap(): Map<string, string> {
  const reversed = new Map<string, string>();
  try {
    const parsed = JSON.parse(process.env.EVOLUTION_GROUP_MAP_JSON || "{}");
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

function hashSender(sender: string): string {
  const salt = process.env.WA_OBSERVER_SENDER_HASH_SALT || "descontos-bot-observer";
  return createHash("sha256").update(`${salt}:${sender}`).digest("hex");
}
