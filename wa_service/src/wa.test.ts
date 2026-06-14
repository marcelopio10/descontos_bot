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

import makeWASocket from "@whiskeysockets/baileys";
import { getAuthDir, getWaVersionOverride, listGroups, resolveGroupJid, sendImage, sendText, connect, collectObservedMessages } from "./wa.js";
import { resetObserverBufferForTests } from "./observer.js";

const mockSock = {
  groupFetchAllParticipating: vi.fn(),
  groupMetadata: vi.fn(),
  sendMessage: vi.fn().mockResolvedValue(undefined),
  ev: { on: vi.fn() },
  user: { id: "5511999999999@s.whatsapp.net" },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(makeWASocket).mockReturnValue(mockSock as never);
  resetObserverBufferForTests();
  delete process.env.WA_AUTH_DIR;
  delete process.env.WA_VERSION;
  delete process.env.WA_OBSERVER_ENABLED;
  delete process.env.WA_OBSERVER_GROUP_JIDS;
  delete process.env.WA_OBSERVER_LOOKBACK_HOURS;
  delete process.env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP;
  delete process.env.WA_OBSERVER_SENDER_HASH_SALT;
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

describe("getWaVersionOverride", () => {
  it("retorna undefined sem WA_VERSION", () => {
    delete process.env.WA_VERSION;
    expect(getWaVersionOverride()).toBeUndefined();
  });

  it("interpreta WA_VERSION no formato vírgula", () => {
    process.env.WA_VERSION = "2,3000,1026152044";
    expect(getWaVersionOverride()).toEqual([2, 3000, 1026152044]);
  });

  it("rejeita WA_VERSION inválida", () => {
    process.env.WA_VERSION = "foo";
    expect(() => getWaVersionOverride()).toThrow("WA_VERSION inválida");
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

  it("aceita JID direto, mas valida o grupo para preparar metadados de criptografia", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({
      "120363000000000001@g.us": { subject: "descontos.bot" },
    });

    const jid = await resolveGroupJid("120363000000000001@g.us", mockSock as never);

    expect(jid).toBe("120363000000000001@g.us");
    expect(mockSock.groupFetchAllParticipating).toHaveBeenCalledOnce();
  });

  it("lança erro descritivo quando JID direto não participa da conta", async () => {
    mockSock.groupFetchAllParticipating.mockResolvedValue({});

    await expect(resolveGroupJid("120363000000999999@g.us", mockSock as never)).rejects.toThrow(
      'Grupo JID "120363000000999999@g.us" não encontrado'
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

describe("messages observer", () => {
  function getMessagesUpsertHandler() {
    const call = mockSock.ev.on.mock.calls.find(([event]) => event === "messages.upsert");
    expect(call).toBeTruthy();
    return call?.[1] as (payload: { messages: Array<Record<string, unknown>> }) => Promise<void>;
  }

  it("não consulta metadados nem registra mensagens quando o observer está desligado", async () => {
    await connect();
    const handler = getMessagesUpsertHandler();

    await handler({
      messages: [
        {
          key: { id: "MSG1", remoteJid: "120363000000000001@g.us", participant: "a@s.whatsapp.net" },
          messageTimestamp: 1781220000,
          message: { conversation: "Oferta R$ 99" },
        },
      ],
    });

    expect(mockSock.groupMetadata).not.toHaveBeenCalled();
    expect(await collectObservedMessages()).toEqual({ enabled: false, messages: [] });
  });

  it("consulta metadados somente para grupos allowlisted quando o observer está ligado", async () => {
    process.env.WA_OBSERVER_ENABLED = "true";
    process.env.WA_OBSERVER_GROUP_JIDS = "120363000000000001@g.us";
    process.env.WA_OBSERVER_LOOKBACK_HOURS = "9999";
    process.env.WA_OBSERVER_SENDER_HASH_SALT = "local-salt";
    mockSock.groupMetadata.mockResolvedValue({ subject: "Ofertas A" });

    await connect();
    const handler = getMessagesUpsertHandler();
    await handler({
      messages: [
        {
          key: { id: "MSG1", remoteJid: "120363000000000001@g.us", participant: "a@s.whatsapp.net" },
          messageTimestamp: 1781220000,
          message: { conversation: "Oferta R$ 99" },
        },
        {
          key: { id: "MSG2", remoteJid: "120363000000000002@g.us", participant: "b@s.whatsapp.net" },
          messageTimestamp: 1781220000,
          message: { conversation: "Outro grupo R$ 88" },
        },
      ],
    });

    expect(mockSock.groupMetadata).toHaveBeenCalledOnce();
    expect(mockSock.groupMetadata).toHaveBeenCalledWith("120363000000000001@g.us");
    const collected = await collectObservedMessages();
    expect(collected.enabled).toBe(true);
    expect(collected.messages).toHaveLength(1);
    expect(collected.messages[0]).toMatchObject({
      message_id: "MSG1",
      group_jid: "120363000000000001@g.us",
      group_subject: "Ofertas A",
    });
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
      { text: "Oferta especial" },
      { useUserDevicesCache: false, useCachedGroupMetadata: false }
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
      },
      { useUserDevicesCache: false, useCachedGroupMetadata: false }
    );
    expect(result.message_id).toBe("img123");
  });
});
