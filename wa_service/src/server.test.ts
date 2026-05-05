import { describe, it, expect, vi, beforeEach } from "vitest";
import request from "supertest";

// Mock wa module before importing app
vi.mock("./wa.js", () => ({
  connect: vi.fn().mockResolvedValue(undefined),
  getStatus: vi.fn(),
  listGroups: vi.fn(),
  sendBatch: vi.fn(),
  sendText: vi.fn(),
}));

import { app } from "./server.js";
import { getStatus, listGroups, sendBatch, sendText } from "./wa.js";

const mockGetStatus = vi.mocked(getStatus);
const mockListGroups = vi.mocked(listGroups);
const mockSendBatch = vi.mocked(sendBatch);
const mockSendText = vi.mocked(sendText);

beforeEach(() => {
  vi.clearAllMocks();
});

const validPayload = {
  target: "descontos.bot",
  items: [
    { id: "MLB001", image_path: "/tmp/a.jpg", text_path: "/tmp/a.txt" },
    { id: "MLB002", image_path: "/tmp/b.jpg", text_path: "/tmp/b.txt" },
  ],
};

describe("GET /status", () => {
  it("retorna connected: false antes de conectar", async () => {
    mockGetStatus.mockReturnValue({ connected: false, jid: null });
    const res = await request(app).get("/status");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ connected: false, jid: null });
  });

  it("retorna connected: true após conexão", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "5511999@s.whatsapp.net" });
    const res = await request(app).get("/status");
    expect(res.status).toBe(200);
    expect(res.body.connected).toBe(true);
    expect(res.body.jid).toBe("5511999@s.whatsapp.net");
  });
});

describe("POST /send — validações", () => {
  it("retorna 400 se target ausente", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    const res = await request(app).post("/send").send({ items: validPayload.items });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/target/);
  });

  it("retorna 400 se items ausente", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    const res = await request(app).post("/send").send({ target: "descontos.bot" });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/items/);
  });

  it("retorna 400 se items for array vazio", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    const res = await request(app).post("/send").send({ target: "descontos.bot", items: [] });
    expect(res.status).toBe(400);
  });

  it("retorna 503 se socket desconectado", async () => {
    mockGetStatus.mockReturnValue({ connected: false, jid: null });
    const res = await request(app).post("/send").send(validPayload);
    expect(res.status).toBe(503);
    expect(res.body.error).toMatch(/não conectado/);
  });
});

describe("POST /send — happy path", () => {
  it("retorna 200 com sent:2, errors:0 e chama sendBatch corretamente", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    mockSendBatch.mockResolvedValue({ sent: 2, errors: 0, failures: [] });

    const res = await request(app).post("/send").send(validPayload);
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ sent: 2, errors: 0, failures: [] });
    expect(mockSendBatch).toHaveBeenCalledWith("descontos.bot", validPayload.items);
  });

  it("retorna sent:1 errors:1 com failures quando um item falha", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    mockSendBatch.mockResolvedValue({
      sent: 1,
      errors: 1,
      failures: [{ id: "MLB002", reason: "Arquivo de imagem não encontrado: /tmp/b.jpg" }],
    });

    const res = await request(app).post("/send").send(validPayload);
    expect(res.status).toBe(200);
    expect(res.body.sent).toBe(1);
    expect(res.body.errors).toBe(1);
    expect(res.body.failures[0].id).toBe("MLB002");
  });
});

describe("POST /send-message", () => {
  it("retorna 400 se destination ausente", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    const res = await request(app).post("/send-message").send({ message: "Oferta" });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/destination/);
  });

  it("retorna 400 se message ausente", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    const res = await request(app).post("/send-message").send({ destination: "descontos.bot" });
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/message/);
  });

  it("retorna 503 se socket desconectado", async () => {
    mockGetStatus.mockReturnValue({ connected: false, jid: null });
    const res = await request(app)
      .post("/send-message")
      .send({ destination: "descontos.bot", message: "Oferta" });
    expect(res.status).toBe(503);
    expect(res.body.error).toMatch(/não conectado/);
  });

  it("envia mensagem de texto quando conectado", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    mockSendText.mockResolvedValue({
      success: true,
      message_id: "abc123",
      sent_at: "2026-04-29T10:30:00.000Z",
    });

    const res = await request(app)
      .post("/send-message")
      .send({ destination: "descontos.bot", message: "Oferta" });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({
      success: true,
      message_id: "abc123",
      sent_at: "2026-04-29T10:30:00.000Z",
    });
    expect(mockSendText).toHaveBeenCalledWith("descontos.bot", "Oferta", undefined);
  });

  it("repassa image_url quando informado", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    mockSendText.mockResolvedValue({
      success: true,
      message_id: "img123",
      sent_at: "2026-04-29T10:30:00.000Z",
    });

    const res = await request(app)
      .post("/send-message")
      .send({
        destination: "descontos.bot",
        message: "Oferta",
        image_url: "https://example.com/produto.jpg",
      });

    expect(res.status).toBe(200);
    expect(mockSendText).toHaveBeenCalledWith(
      "descontos.bot",
      "Oferta",
      "https://example.com/produto.jpg"
    );
  });
});

describe("GET /debug/groups", () => {
  it("retorna 503 se socket desconectado", async () => {
    mockGetStatus.mockReturnValue({ connected: false, jid: null });
    const res = await request(app).get("/debug/groups");
    expect(res.status).toBe(503);
  });

  it("lista grupos quando conectado", async () => {
    mockGetStatus.mockReturnValue({ connected: true, jid: "jid" });
    mockListGroups.mockResolvedValue([
      { jid: "120363000000000001@g.us", subject: "descontos.bot" },
    ]);

    const res = await request(app).get("/debug/groups");

    expect(res.status).toBe(200);
    expect(res.body).toEqual({
      groups: [{ jid: "120363000000000001@g.us", subject: "descontos.bot" }],
    });
  });
});
