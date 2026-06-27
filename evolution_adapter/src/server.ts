import express, { type Request, type Response } from "express";
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
  if (!message || typeof message !== "string") {
    res.status(400).json({ error: "Campo 'message' é obrigatório (string)" });
    return;
  }
  if (image_url !== undefined && typeof image_url !== "string") {
    res.status(400).json({ error: "Campo 'image_url' deve ser string quando informado" });
    return;
  }

  try {
    const config = getConfig();
    const number = resolveDestination(destination, config.groupMapJson);
    const result = image_url
      ? await sendMedia(config, number, message, image_url)
      : await sendText(config, number, message);
    res.json(result);
  } catch (err: unknown) {
    res.status(500).json({ error: errorMessage(err) });
  }
});

app.post("/send", async (_req: Request, res: Response) => {
  res.status(501).json({
    error: "Endpoint /send ainda não implementado no evolution_adapter. Use /send-message com image_url pública ou implemente conversão local para base64.",
  });
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
