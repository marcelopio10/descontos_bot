import express, { type Request, type Response } from "express";
import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import { getConfig } from "./config.js";
import { loadEnvFromNearestFile } from "./env.js";
import { getConnectionState, sendMedia, sendText } from "./evolutionClient.js";
import { resolveDestination } from "./groupMap.js";
import { collectObservedMessages, listObserverGroups, storeWebhookPayload } from "./observerBuffer.js";

export const app = express();
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req: Request, res: Response) => {
  res.json({ ok: true, service: "evolution_adapter" });
});

app.get("/status", async (_req: Request, res: Response) => {
  try {
    const state = await getConnectionState(getConfig());
    res.json({ connected: state.connected, jid: state.jid });
  } catch (err: unknown) {
    res.status(503).json({ connected: false, jid: null, error: errorMessage(err) });
  }
});

app.post("/send-message", async (req: Request, res: Response) => {
  const { destination, message, image_url } = req.body as {
    destination?: string;
    message?: string;
    image_url?: string;
  };

  if (!destination || typeof destination !== "string") {
    res.status(400).json({ error: "Campo 'destination' é obrigatório (string)" });
    return;
  }
  if (typeof message !== "string" || !message.trim()) {
    res.status(400).json({ error: "Campo 'message' é obrigatório (string)" });
    return;
  }
  if (image_url !== undefined && typeof image_url !== "string") {
    res.status(400).json({ error: "Campo 'image_url' deve ser string quando informado" });
    return;
  }

  try {
    const config = getConfig();
    const state = await getConnectionState(config);
    if (!state.connected) {
      res.status(503).json({ error: "WhatsApp não conectado na Evolution API. Verifique a instância de envio." });
      return;
    }
    const number = resolveDestination(destination, config.groupMapJson);
    const text = message.trim();
    const result = image_url
      ? await sendMedia(config, number, text, image_url)
      : await sendText(config, number, text);
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: errorMessage(err) });
  }
});

app.post("/send", async (_req: Request, res: Response) => {
  const { target, items } = _req.body as {
    target?: string;
    items?: Array<{ id?: string; image_path?: string; text_path?: string }>;
  };

  if (!target || typeof target !== "string") {
    res.status(400).json({ error: "Campo 'target' é obrigatório (string)" });
    return;
  }
  if (!Array.isArray(items) || items.length === 0) {
    res.status(400).json({ error: "Campo 'items' deve ser array não-vazio" });
    return;
  }

  try {
    const config = getConfig();
    const state = await getConnectionState(config);
    if (!state.connected) {
      res.status(503).json({ error: "WhatsApp não conectado na Evolution API. Verifique a instância de envio." });
      return;
    }
    const number = resolveDestination(target, config.groupMapJson);
    const result = { sent: 0, errors: 0, failures: [] as Array<{ id: string; reason: string }> };

    for (const item of items) {
      const id = String(item?.id || "");
      try {
        if (!id || typeof item?.image_path !== "string" || typeof item?.text_path !== "string") {
          throw new Error("Item deve ter id, image_path e text_path string.");
        }
        const [caption, image] = await Promise.all([
          readFile(item.text_path, "utf-8"),
          readFile(item.image_path),
        ]);
        await sendMedia(config, number, caption, image.toString("base64"), basename(item.image_path));
        result.sent++;
      } catch (err: unknown) {
        result.errors++;
        result.failures.push({ id: id || "unknown", reason: errorMessage(err) });
      }
    }

    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: errorMessage(err) });
  }
});

app.get("/observer/groups", (_req: Request, res: Response) => {
  res.json(listObserverGroups());
});

app.post("/observer/collect", (_req: Request, res: Response) => {
  res.json(collectObservedMessages());
});

app.post("/webhook/whatsapp", (req: Request, res: Response) => {
  const config = getConfig();
  const result = storeWebhookPayload(req.body || {}, config.instanciaObserver);
  res.json({ ok: true, ...result });
});

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function startServer() {
  const config = getConfig();
  return app.listen(config.port, config.host, () => {
    console.log(`[evolution_adapter] rodando em http://${config.host}:${config.port}`);
  });
}

if (!process.env.VITEST) {
  const loadedEnvPath = loadEnvFromNearestFile();
  if (loadedEnvPath) {
    console.log(`[evolution_adapter] variáveis carregadas de ${loadedEnvPath}`);
  }
  startServer();
}
