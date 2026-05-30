import { describe, it, expect, vi, beforeEach } from "vitest";
import { readFile, writeFile, unlink } from "fs/promises";
import os from "os";
import path from "path";

// Mock Baileys before importing wa.ts
vi.mock("@whiskeysockets/baileys", () => ({
  default: vi.fn(),
  useMultiFileAuthState: vi.fn().mockResolvedValue({
    state: { creds: {}, keys: {} },
    saveCreds: vi.fn(),
  }),
  fetchLatestBaileysVersion: vi.fn().mockResolvedValue({ version: [2, 2413, 1] }),
  makeCacheableSignalKeyStore: vi.fn((keys: unknown) => keys),
  DisconnectReason: { loggedOut: 401 },
}));
vi.mock("qrcode-terminal", () => ({ default: { generate: vi.fn() } }));
vi.mock("pino", () => ({ default: vi.fn(() => ({ level: "silent" })) }));

import { getAuthDir, listGroups, resolveGroupJid, sendImage, sendText } from "./wa.js";

const mockSock = {
  groupFetchAllParticipating: vi.fn(),
  sendMessage: vi.fn().mockResolvedValue(undefined),
  ev: { on: vi.fn() },
  user: { id: "5511999999999@s.whatsapp.net" },
};

beforeEach(() => {
  vi.clearAllMocks();
  delete process.env.WA_AUTH_DIR;
});

describe("getAuthDir", () => {
  it("usa auth_state como diretório padrão da sessão Baileys", () => {
    expect(getAuthDir()).toBe(path.resolve("auth_state"));
  });

  it("permite sobrescrever o diretório via WA_AUTH_DIR", () => {
    process.env.WA_AUTH_DIR = "../wa_session";
    expect(getAuthDir()).toBe(path.resolve("../wa_session"));
  });
});

describe("resolveGroupJid", () => {
  it("retorna JID correto quando grupo existe", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000001@g.us": { subject: "descontos.bot" },
      "120363000000000002@g.us": { subject: "outro grupo" },
    });

    const jid = await resolveGroupJid("descontos.bot", mockSock as never);
    expect(jid).toBe("120363000000000001@g.us");
  });

  it("lança erro descritivo quando grupo não existe", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000002@g.us": { subject: "outro grupo" },
    });

    await expect(resolveGroupJid("descontos.bot", mockSock as never)).rejects.toThrow(
      'Grupo "descontos.bot" não encontrado'
    );
  });
});

describe("listGroups", () => {
  it("lista grupos ordenados por nome", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000002@g.us": { subject: "Zulu" },
      "120363000000000001@g.us": { subject: "Alpha" },
    });

    await expect(listGroups(mockSock as never)).resolves.toEqual([
      { jid: "120363000000000001@g.us", subject: "Alpha" },
      { jid: "120363000000000002@g.us", subject: "Zulu" },
    ]);
  });
});

describe("sendImage", () => {
  it("lê arquivo e chama sendMessage com image Buffer e caption", async () => {
    const tmpDir = os.tmpdir();
    const imgPath = path.join(tmpDir, "test_image.jpg");
    const captionText = "🔥 Oferta especial 50% OFF — confira: https://…";

    // Cria arquivo de imagem dummy
    await writeFile(imgPath, Buffer.from([0xff, 0xd8, 0xff, 0xe0]));

    await sendImage("120363000000000001@g.us", imgPath, captionText, mockSock as never);

    expect(mockSock.sendMessage).toHaveBeenCalledOnce();
    const [jid, payload] = mockSock.sendMessage.mock.calls[0] as [string, { image: Buffer; caption: string }];
    expect(jid).toBe("120363000000000001@g.us");
    expect(Buffer.isBuffer(payload.image)).toBe(true);
    const originalBuffer = await readFile(imgPath);
    expect(payload.image).toEqual(originalBuffer);
    expect(payload.caption).toBe(captionText);

    await unlink(imgPath);
  });

  it("propaga erro quando arquivo de imagem não existe", async () => {
    await expect(
      sendImage("jid@g.us", "/caminho/inexistente/foto.jpg", "caption", mockSock as never)
    ).rejects.toThrow("Arquivo de imagem não encontrado");
  });
});

describe("sendText", () => {
  it("resolve grupo e chama sendMessage com texto", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000001@g.us": { subject: "descontos.bot" },
    });
    mockSock.sendMessage.mockResolvedValue({
      key: { id: "abc123" },
    });

    const result = await sendText("descontos.bot", "Oferta especial", undefined, mockSock as never);

    expect(mockSock.sendMessage).toHaveBeenCalledWith(
      "120363000000000001@g.us",
      { text: "Oferta especial" }
    );
    expect(result.success).toBe(true);
    expect(result.message_id).toBe("abc123");
    expect(result.sent_at).toBeTruthy();
  });

  it("envia imagem por URL com texto como legenda quando imageUrl é informado", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000001@g.us": { subject: "descontos.bot" },
    });
    mockSock.sendMessage.mockResolvedValue({
      key: { id: "img123" },
    });

    const result = await sendText(
      "descontos.bot",
      "Oferta especial",
      "https://example.com/produto.jpg",
      mockSock as never
    );

    expect(mockSock.sendMessage).toHaveBeenCalledWith(
      "120363000000000001@g.us",
      {
        image: { url: "https://example.com/produto.jpg" },
        caption: "Oferta especial",
      }
    );
    expect(result.message_id).toBe("img123");
  });
});
