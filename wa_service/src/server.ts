import express, { type Request, type Response } from "express";
import {
  connect,
  getGroupDebug,
  getStatus,
  listGroups,
  sendBatch,
  sendText,
  type SendItem,
} from "./wa.js";

const app = express();
app.use(express.json());

const HOST = "127.0.0.1";
const PORT = 8787;

app.get("/status", (_req: Request, res: Response) => {
  res.json(getStatus());
});

app.post("/send", async (req: Request, res: Response) => {
  const { target, items } = req.body as {
    target?: string;
    items?: SendItem[];
  };

  if (!target || typeof target !== "string") {
    res.status(400).json({ error: "Campo 'target' é obrigatório (string)" });
    return;
  }
  if (!Array.isArray(items) || items.length === 0) {
    res.status(400).json({ error: "Campo 'items' deve ser array não-vazio" });
    return;
  }

  const status = getStatus();
  if (!status.connected) {
    res
      .status(503)
      .json({ error: "WhatsApp não conectado. Aguarde o pareamento via QR." });
    return;
  }

  try {
    const result = await sendBatch(target, items);
    res.json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`[server] Erro no /send: ${message}`);
    res.status(500).json({ error: message });
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

  const status = getStatus();
  if (!status.connected) {
    res
      .status(503)
      .json({ error: "WhatsApp não conectado. Aguarde o pareamento via QR." });
    return;
  }

  try {
    const result = await sendText(destination, message, image_url || undefined);
    res.json(result);
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    console.error(`[server] Erro no /send-message: ${errorMessage}`);
    res.status(500).json({ error: errorMessage });
  }
});

// Endpoint de debug — últimas N mensagens de um JID (para teste de integração)
app.get("/debug/last-messages", async (req: Request, res: Response) => {
  res.status(501).json({ error: "Não implementado nesta versão" });
});

app.get("/debug/groups", async (_req: Request, res: Response) => {
  const status = getStatus();
  if (!status.connected) {
    res
      .status(503)
      .json({ error: "WhatsApp não conectado. Aguarde o pareamento via QR." });
    return;
  }

  try {
    res.json({ groups: await listGroups() });
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    res.status(500).json({ error: errorMessage });
  }
});

app.get("/debug/group/:jid", async (req: Request, res: Response) => {
  const status = getStatus();
  if (!status.connected) {
    res
      .status(503)
      .json({ error: "WhatsApp não conectado. Aguarde o pareamento via QR." });
    return;
  }

  try {
    res.json(await getGroupDebug(req.params.jid));
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    res.status(500).json({ error: errorMessage });
  }
});

function startServer() {
  return app.listen(PORT, HOST, () => {
    console.log(`[server] wa-service rodando em http://${HOST}:${PORT}`);
    connect().catch((err: unknown) => {
      console.error("[wa] Falha ao conectar:", err);
    });
  });
}

if (!process.env.VITEST) {
  startServer();
}

export { app, startServer };
