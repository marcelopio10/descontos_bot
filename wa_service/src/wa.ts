import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  type WASocket,
} from "@whiskeysockets/baileys";
import { Boom } from "@hapi/boom";
import { readFile } from "fs/promises";
import { existsSync } from "fs";
import path from "path";
import qrcode from "qrcode-terminal";
import pino from "pino";

const logger = pino({ level: "silent" });

const DEFAULT_AUTH_DIR = "auth_state";

export function getAuthDir(): string {
  return path.resolve(process.env.WA_AUTH_DIR || DEFAULT_AUTH_DIR);
}

export interface SendItem {
  id: string;
  image_path: string;
  text_path: string;
}

export interface SendResult {
  sent: number;
  errors: number;
  failures: Array<{ id: string; reason: string }>;
}

export interface SendTextResult {
  success: boolean;
  message_id: string;
  sent_at: string;
}

export interface WhatsAppGroup {
  jid: string;
  subject: string;
}

let sock: WASocket | null = null;
let isConnected = false;
let connectedJid: string | null = null;
// Cache: group subject -> JID
const groupJidCache = new Map<string, string>();

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function jitter(minMs: number, maxMs: number) {
  return Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
}

export function getStatus() {
  return { connected: isConnected, jid: connectedJid };
}

export async function connect(): Promise<void> {
  const { state, saveCreds } = await useMultiFileAuthState(getAuthDir());
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    printQRInTerminal: false,
    browser: ["descontos-bot", "Chrome", "120.0.0"],
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log("\n[wa] Escaneie o QR code com seu celular:\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "close") {
      isConnected = false;
      connectedJid = null;
      const shouldReconnect =
        (lastDisconnect?.error as Boom)?.output?.statusCode !==
        DisconnectReason.loggedOut;
      console.log(`[wa] Conexão fechada. Reconectando: ${shouldReconnect}`);
      if (shouldReconnect) {
        setTimeout(() => connect(), 3000);
      }
    }

    if (connection === "open") {
      isConnected = true;
      connectedJid = sock?.user?.id ?? null;
      console.log(`[wa] Conectado! JID: ${connectedJid}`);
    }
  });
}

export async function resolveGroupJid(
  targetName: string,
  sockInstance?: WASocket | null
): Promise<string> {
  const s = sockInstance ?? sock;
  if (!s) throw new Error("Socket não conectado");

  const shouldUseCache = sockInstance == null;
  const cached = shouldUseCache ? groupJidCache.get(targetName) : undefined;
  if (cached) return cached;

  const groups = await s.groupFetchAllParticipating();
  for (const [jid, meta] of Object.entries(groups)) {
    if (meta.subject === targetName) {
      if (shouldUseCache) {
        groupJidCache.set(targetName, jid);
      }
      return jid;
    }
  }
  throw new Error(`Grupo "${targetName}" não encontrado no WhatsApp`);
}

export async function listGroups(sockInstance?: WASocket | null): Promise<WhatsAppGroup[]> {
  const s = sockInstance ?? sock;
  if (!s) throw new Error("Socket não conectado");

  const groups = await s.groupFetchAllParticipating();
  return Object.entries(groups)
    .map(([jid, meta]) => ({
      jid,
      subject: meta.subject,
    }))
    .sort((a, b) => a.subject.localeCompare(b.subject, "pt-BR"));
}

export async function sendImage(
  jid: string,
  imagePath: string,
  caption: string,
  sockInstance?: WASocket | null
): Promise<void> {
  const s = sockInstance ?? sock;
  if (!s) throw new Error("Socket não conectado");

  if (!existsSync(imagePath)) {
    throw new Error(`Arquivo de imagem não encontrado: ${imagePath}`);
  }

  const imageBuffer = await readFile(imagePath);
  await s.sendMessage(jid, { image: imageBuffer, caption });
}

export async function sendText(
  target: string,
  message: string,
  imageUrl?: string,
  sockInstance?: WASocket | null
): Promise<SendTextResult> {
  const s = sockInstance ?? sock;
  if (!s) throw new Error("Socket não conectado");

  const jid = await resolveGroupJid(target, s);
  const result = imageUrl
    ? await s.sendMessage(jid, { image: { url: imageUrl }, caption: message })
    : await s.sendMessage(jid, { text: message });
  return {
    success: true,
    message_id: result?.key?.id ?? "",
    sent_at: new Date().toISOString(),
  };
}

export async function sendBatch(
  target: string,
  items: SendItem[]
): Promise<SendResult> {
  if (!isConnected || !sock) {
    throw new Error("WhatsApp não conectado — inicie o serviço e pareie o QR");
  }

  const jid = await resolveGroupJid(target);
  const result: SendResult = { sent: 0, errors: 0, failures: [] };

  for (const item of items) {
    try {
      const caption = await readFile(item.text_path, "utf-8");
      await sendImage(jid, item.image_path, caption);
      result.sent++;
      console.log(`[wa] Enviado: ${item.id}`);
      // Mantém jitter igual ao wa_poster.py original (5.5s–9.5s)
      await sleep(jitter(5500, 9500));
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : String(err);
      console.error(`[wa] Erro em ${item.id}: ${reason}`);
      result.errors++;
      result.failures.push({ id: item.id, reason });
    }
  }

  return result;
}
