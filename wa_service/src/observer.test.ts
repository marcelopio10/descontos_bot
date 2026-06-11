import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  collectObservedMessages,
  getObserverConfig,
  listObserverGroups,
  normalizeIncomingMessage,
  recordObservedMessage,
  resetObserverBufferForTests,
} from "./observer.js";

const GROUPS = [
  { jid: "120363000000000001@g.us", subject: "Ofertas A" },
  { jid: "120363000000000002@g.us", subject: "Ofertas B" },
];

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-06-11T23:30:00.000Z"));
  delete process.env.WA_OBSERVER_ENABLED;
  delete process.env.WA_OBSERVER_GROUP_JIDS;
  delete process.env.WA_OBSERVER_LOOKBACK_HOURS;
  delete process.env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP;
  delete process.env.WA_OBSERVER_SENDER_HASH_SALT;
  resetObserverBufferForTests();
});

describe("getObserverConfig", () => {
  it("mantém observer desligado e sem allowlist por padrão", () => {
    expect(getObserverConfig()).toEqual({
      enabled: false,
      groupJids: [],
      lookbackHours: 24,
      maxMessagesPerGroup: 300,
      senderHashSalt: "descontos-bot-observer",
    });
  });

  it("lê allowlist explícita e limites por env", () => {
    process.env.WA_OBSERVER_ENABLED = "true";
    process.env.WA_OBSERVER_GROUP_JIDS = "120363000000000001@g.us, 120363000000000002@g.us";
    process.env.WA_OBSERVER_LOOKBACK_HOURS = "12";
    process.env.WA_OBSERVER_MAX_MESSAGES_PER_GROUP = "50";
    process.env.WA_OBSERVER_SENDER_HASH_SALT = "local-salt";

    expect(getObserverConfig()).toEqual({
      enabled: true,
      groupJids: ["120363000000000001@g.us", "120363000000000002@g.us"],
      lookbackHours: 12,
      maxMessagesPerGroup: 50,
      senderHashSalt: "local-salt",
    });
  });
});

describe("listObserverGroups", () => {
  it("nunca lista grupos quando observer está desligado", () => {
    expect(listObserverGroups(GROUPS)).toEqual({ enabled: false, groups: [] });
  });

  it("lista apenas grupos permitidos pela allowlist", () => {
    process.env.WA_OBSERVER_ENABLED = "true";
    process.env.WA_OBSERVER_GROUP_JIDS = "120363000000000002@g.us";

    expect(listObserverGroups(GROUPS)).toEqual({
      enabled: true,
      groups: [{ jid: "120363000000000002@g.us", subject: "Ofertas B" }],
    });
  });
});

describe("normalizeIncomingMessage", () => {
  it("normaliza texto, urls, imagem e hash do remetente sem expor telefone", () => {
    process.env.WA_OBSERVER_SENDER_HASH_SALT = "salt";
    const message = normalizeIncomingMessage({
      key: {
        id: "MSG1",
        remoteJid: "120363000000000001@g.us",
        participant: "556199999999@s.whatsapp.net",
      },
      messageTimestamp: 1781220000,
      message: {
        imageMessage: {
          caption: "Air Fryer por R$ 199,90 https://amzn.to/oferta",
        },
      },
    } as never, "Ofertas A");

    expect(message).toMatchObject({
      message_id: "MSG1",
      group_jid: "120363000000000001@g.us",
      group_subject: "Ofertas A",
      sent_at: "2026-06-11T23:20:00.000Z",
      text: "Air Fryer por R$ 199,90 https://amzn.to/oferta",
      has_image: true,
      urls: ["https://amzn.to/oferta"],
      raw_type: "imageMessage",
      collected_at: "2026-06-11T23:30:00.000Z",
    });
    expect(message?.sender_hash).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(message)).not.toContain("556199999999");
  });
});

describe("recordObservedMessage / collectObservedMessages", () => {
  it("ignora mensagens quando observer está desligado", () => {
    recordObservedMessage({ key: { id: "MSG1", remoteJid: "120363000000000001@g.us" }, message: { conversation: "oi" } } as never, "Ofertas A");

    expect(collectObservedMessages()).toEqual({ enabled: false, messages: [] });
  });

  it("coleta apenas mensagens de grupos allowlisted dentro da janela", () => {
    process.env.WA_OBSERVER_ENABLED = "true";
    process.env.WA_OBSERVER_GROUP_JIDS = "120363000000000001@g.us";
    process.env.WA_OBSERVER_LOOKBACK_HOURS = "24";

    recordObservedMessage({ key: { id: "MSG1", remoteJid: "120363000000000001@g.us", participant: "a@s.whatsapp.net" }, messageTimestamp: 1781220000, message: { conversation: "Oferta Amazon R$ 99 https://amazon.com.br/x" } } as never, "Ofertas A");
    recordObservedMessage({ key: { id: "MSG2", remoteJid: "120363000000000002@g.us", participant: "b@s.whatsapp.net" }, messageTimestamp: 1781220000, message: { conversation: "Outro grupo" } } as never, "Ofertas B");
    recordObservedMessage({ key: { id: "MSG3", remoteJid: "120363000000000001@g.us", participant: "c@s.whatsapp.net" }, messageTimestamp: 1781000000, message: { conversation: "Mensagem antiga" } } as never, "Ofertas A");

    expect(collectObservedMessages()).toEqual({
      enabled: true,
      messages: [
        expect.objectContaining({
          message_id: "MSG1",
          group_jid: "120363000000000001@g.us",
          group_subject: "Ofertas A",
          text: "Oferta Amazon R$ 99 https://amazon.com.br/x",
        }),
      ],
    });
  });
});
