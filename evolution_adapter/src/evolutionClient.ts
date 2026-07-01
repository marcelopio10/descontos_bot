import type { AdapterConfig } from "./config.js";

export interface EvolutionConnectionState {
  connected: boolean;
  jid: string | null;
  rawState: string;
}

export interface EvolutionSendResult {
  success: boolean;
  message_id: string;
  sent_at: string;
}

function credentialHeaderName(): string {
  return ["api", "key"].join("");
}

async function evolutionRequest(
  config: AdapterConfig,
  method: string,
  path: string,
  data?: Record<string, unknown>
): Promise<Record<string, any>> {
  if (!config.evolutionCredential) {
    throw new Error("Credencial da Evolution API não configurada.");
  }
  const headers: Record<string, string> = {
    Accept: "application/json",
    [credentialHeaderName()]: config.evolutionCredential,
  };
  let body: string | undefined;
  if (data !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(data);
  }
  const response = await fetch(`${config.evolutionBaseUrl}${path}`, { method, headers, body });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(String(payload?.message || payload?.error || `Evolution API HTTP ${response.status}`));
  }
  return payload;
}

export async function getConnectionState(config: AdapterConfig): Promise<EvolutionConnectionState> {
  const payload = await evolutionRequest(config, "GET", `/instance/connectionState/${config.instanciaEnvio}`);
  const state = String(payload?.instance?.state || payload?.state || "");
  return {
    connected: state === "open",
    jid: payload?.instance?.instanceName || config.instanciaEnvio,
    rawState: state,
  };
}

export async function sendText(
  config: AdapterConfig,
  number: string,
  text: string
): Promise<EvolutionSendResult> {
  const payload = await evolutionRequest(config, "POST", `/message/sendText/${config.instanciaEnvio}`, {
    number,
    text,
  });
  return normalizeSendResult(payload);
}

export async function sendMedia(
  config: AdapterConfig,
  number: string,
  caption: string,
  media: string,
  fileName?: string
): Promise<EvolutionSendResult> {
  const mediaInput = await prepareMediaInput(media, fileName);
  const payload = await evolutionRequest(config, "POST", `/message/sendMedia/${config.instanciaEnvio}`, {
    number,
    mediatype: "image",
    mimetype: mediaInput.mimetype,
    caption,
    media: mediaInput.media,
    fileName: mediaInput.fileName,
  });
  return normalizeSendResult(payload);
}

function normalizeSendResult(payload: Record<string, any>): EvolutionSendResult {
  const messageId =
    payload?.key?.id ||
    payload?.message?.key?.id ||
    payload?.id ||
    payload?.messageId ||
    "";
  return {
    success: true,
    message_id: String(messageId),
    sent_at: new Date().toISOString(),
  };
}

function inferImageMimeType(media: string): string {
  const lower = media.toLowerCase().split("?")[0];
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".webp")) return "image/webp";
  return "image/jpeg";
}

async function prepareMediaInput(media: string, fileName?: string): Promise<{ media: string; mimetype: string; fileName: string }> {
  if (fileName || hasExplicitImageExtension(media)) {
    const mediaName = fileName || inferFileName(media);
    return {
      media,
      mimetype: inferImageMimeType(mediaName),
      fileName: mediaName,
    };
  }

  const response = await fetch(media, {
    headers: {
      Accept: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
      "User-Agent": "Mozilla/5.0 (compatible; descontos.bot/evolution-adapter)",
    },
  });
  if (!response.ok) {
    throw new Error(`Falha ao baixar mídia da oferta: HTTP ${response.status}`);
  }
  const mimetype = normalizeImageContentType(response.headers.get("content-type"));
  const buffer = Buffer.from(await response.arrayBuffer());
  return {
    media: buffer.toString("base64"),
    mimetype,
    fileName: `offer.${extensionFromMimeType(mimetype)}`,
  };
}

function hasExplicitImageExtension(media: string): boolean {
  const lower = media.toLowerCase().split("?")[0];
  return lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".png") || lower.endsWith(".webp");
}

function normalizeImageContentType(value: string | null): string {
  const contentType = String(value || "").split(";")[0].trim().toLowerCase();
  if (contentType === "image/png") return "image/png";
  if (contentType === "image/webp") return "image/webp";
  return "image/jpeg";
}

function extensionFromMimeType(mimetype: string): string {
  if (mimetype === "image/png") return "png";
  if (mimetype === "image/webp") return "webp";
  return "jpg";
}

function inferFileName(media: string): string {
  try {
    const url = new URL(media);
    const name = url.pathname.split("/").filter(Boolean).pop();
    return name || "oferta.jpg";
  } catch {
    return "oferta.jpg";
  }
}
