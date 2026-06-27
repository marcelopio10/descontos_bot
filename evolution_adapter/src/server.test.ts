import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import request from 'supertest';

vi.mock('./evolutionClient.js', () => ({
  getConnectionState: vi.fn(),
  sendMedia: vi.fn(),
  sendText: vi.fn(),
}));

import { app } from './server.js';
import { getConnectionState, sendMedia, sendText } from './evolutionClient.js';

const mockGetConnectionState = vi.mocked(getConnectionState);
const mockSendMedia = vi.mocked(sendMedia);
const mockSendText = vi.mocked(sendText);

beforeEach(() => {
  vi.clearAllMocks();
  delete process.env.EVOLUTION_GROUP_MAP_PATH;
  process.env.EVOLUTION_GROUP_MAP_JSON = JSON.stringify({
    'descontos.bot': '120363000000001@g.us',
    'descontos.bot - Homologação': '120363000000001@g.us',
  });
  process.env.EVOLUTION_INSTANCIA_ENVIO = 'descontos_envio';
  process.env.EVOLUTION_INSTANCIA_OBSERVER = 'descontos_observer';
  process.env.WA_OBSERVER_ENABLED = 'true';
  process.env.WA_OBSERVER_GROUP_JIDS = '120363000000001@g.us';
});

describe('GET /health', () => {
  it('responde ok', async () => {
    const res = await request(app).get('/health');

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true, service: 'evolution_adapter' });
  });
});

describe('GET /status', () => {
  it('mapeia connectionState open para connected true', async () => {
    mockGetConnectionState.mockResolvedValue({ connected: true, jid: 'descontos_envio', rawState: 'open' });

    const res = await request(app).get('/status');

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ connected: true, jid: 'descontos_envio' });
  });
});

describe('POST /send-message', () => {
  it('valida destination', async () => {
    const res = await request(app).post('/send-message').send({ message: 'Oferta' });

    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/destination/);
  });

  it('envia texto para JID resolvido por mapa', async () => {
    mockSendText.mockResolvedValue({ success: true, message_id: 'MSG1', sent_at: '2026-06-27T12:00:00.000Z' });

    const res = await request(app).post('/send-message').send({ destination: 'descontos.bot', message: 'Oferta' });

    expect(res.status).toBe(200);
    expect(res.body.message_id).toBe('MSG1');
    expect(mockSendText).toHaveBeenCalledWith(expect.any(Object), '120363000000001@g.us', 'Oferta');
  });

  it('envia texto para JID resolvido por arquivo local ignorado pelo Git', async () => {
    const tmpDir = mkdtempSync(join(tmpdir(), 'evolution-map-'));
    const mapPath = join(tmpDir, 'group_map.json');
    writeFileSync(mapPath, JSON.stringify({ 'grupo arquivo': '120363000000002@g.us' }));
    delete process.env.EVOLUTION_GROUP_MAP_JSON;
    process.env.EVOLUTION_GROUP_MAP_PATH = mapPath;
    mockSendText.mockResolvedValue({ success: true, message_id: 'MSG2', sent_at: '2026-06-27T12:00:00.000Z' });

    const res = await request(app).post('/send-message').send({ destination: 'grupo arquivo', message: 'Oferta' });

    expect(res.status).toBe(200);
    expect(res.body.message_id).toBe('MSG2');
    expect(mockSendText).toHaveBeenCalledWith(expect.any(Object), '120363000000002@g.us', 'Oferta');
  });

  it('envia imagem quando image_url é informado', async () => {
    mockSendMedia.mockResolvedValue({ success: true, message_id: 'IMG1', sent_at: '2026-06-27T12:00:00.000Z' });

    const res = await request(app).post('/send-message').send({
      destination: '120363000000001@g.us',
      message: 'Oferta',
      image_url: 'https://example.com/oferta.jpg',
    });

    expect(res.status).toBe(200);
    expect(mockSendMedia).toHaveBeenCalledWith(expect.any(Object), '120363000000001@g.us', 'Oferta', 'https://example.com/oferta.jpg');
  });
});

describe('observer endpoints', () => {
  it('lista grupos allowlisted', async () => {
    const res = await request(app).get('/observer/groups');

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ enabled: true, groups: [{ jid: '120363000000001@g.us', subject: 'descontos.bot - Homologação' }] });
  });

  it('recebe envelope real da Evolution e expõe mensagem normalizada no collect', async () => {
    const payload = {
      event: 'messages.upsert',
      instance: 'descontos_observer',
      destination: 'descontos_observer',
      date_time: '2026-06-27T15:16:46.000Z',
      data: {
        key: { id: 'ABC', remoteJid: '120363000000001@g.us', participant: '556100000000@s.whatsapp.net' },
        messageTimestamp: 1780000000,
        pushName: 'Remetente Teste',
        source: 'unknown',
        status: 'DELIVERY_ACK',
        messageType: 'conversation',
        message: {
          conversation: 'Oferta R$ 99 https://example.com/p',
          messageContextInfo: {},
        },
      },
    };

    const webhook = await request(app).post('/webhook/whatsapp').send(payload);
    const collect = await request(app).post('/observer/collect').send({});

    expect(webhook.status).toBe(200);
    expect(webhook.body.stored).toBe(1);
    expect(collect.body.messages[0].message_id).toBe('ABC');
    expect(collect.body.messages[0].group_subject).toBe('descontos.bot - Homologação');
    expect(collect.body.messages[0].raw_type).toBe('conversation');
    expect(collect.body.messages[0].sender_hash).toMatch(/^[a-f0-9]{64}$/);
    expect(JSON.stringify(collect.body)).not.toContain('556100000000');
  });
});
