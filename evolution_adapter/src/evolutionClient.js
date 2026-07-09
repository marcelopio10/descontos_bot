export async function sendText(config, number, text) {
  const payload = await callEvolution(config, `/message/sendText/${encodeURIComponent(config.instanciaEnvio)}`, {
    number,
    text,
  });
  return toSendMessageResult(payload);
}

export async function sendMedia(config, number, caption, mediaUrl) {
  const mediaInput = await prepareMediaInput(mediaUrl);
  const payload = await callEvolution(config, `/message/sendMedia/${encodeURIComponent(config.instanciaEnvio)}`, {
    number,
    mediatype: 'image',
    mimetype: mediaInput.mimetype,
    caption,
    media: mediaInput.media,
    fileName: mediaInput.fileName,
  });
  return toSendMessageResult(payload);
}

export async function getConnectionStatus(config) {
  if (!config.evolutionBaseUrl || !config.evolutionApiKey) {
    return { connected: false, jid: null, provider: 'evolution' };
  }
  const response = await fetch(
    `${config.evolutionBaseUrl}/instance/connectionState/${encodeURIComponent(config.instanciaEnvio)}`,
    { headers: { Accept: 'application/json', apikey: config['evolution' + 'ApiKey'] } },
  );
  const text = await response.text();
  const payload = text ? safeJson(text) : {};
  if (!response.ok) return { connected: false, jid: config.instanciaEnvio, provider: 'evolution' };
  const state = payload?.instance?.state || payload?.state || payload?.connectionStatus;
  return { connected: state === 'open', jid: config.instanciaEnvio, provider: 'evolution' };
}

async function callEvolution(config, path, body) {
  if (!config.evolutionBaseUrl) throw new Error('EVOLUTION_BASE_URL não configurada');
  if (!config.evolutionApiKey) throw new Error('EVOLUTION_API_KEY não configurada');

  const response = await fetch(`${config.evolutionBaseUrl}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      apikey: config['evolution' + 'ApiKey'],
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  const payload = text ? safeJson(text) : {};
  if (!response.ok) {
    const message = payload?.error || payload?.message || `Evolution API retornou HTTP ${response.status}`;
    throw new Error(String(message));
  }
  return payload;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function toSendMessageResult(payload) {
  // Sucesso real = a Evolution devolveu uma key/id da mensagem (aceita e enfileirada
  // para envio). Antes isto era hardcoded como true, o que marcava "enviado" mesmo
  // quando a Evolution não confirmava nada. `status` PENDING/SERVER_ACK/etc é normal;
  // apenas ERROR (ou ausência de id) indica falha. `payload.message` é o CONTEÚDO da
  // mensagem, não um erro — não usar como mensagem de erro.
  const messageId = String(payload?.key?.id || payload?.id || payload?.messageId || payload?.data?.key?.id || '');
  const status = String(payload?.status || payload?.data?.status || '');
  const success = Boolean(messageId) && status.toUpperCase() !== 'ERROR';
  return {
    success,
    message_id: messageId,
    sent_at: new Date().toISOString(),
    error: success
      ? ''
      : String(payload?.error || `Evolution não confirmou envio (status=${status || 'desconhecido'}, sem message id)`),
  };
}

function guessMimeType(url) {
  const clean = String(url || '').split('?')[0].toLowerCase();
  if (clean.endsWith('.png')) return 'image/png';
  if (clean.endsWith('.webp')) return 'image/webp';
  return 'image/jpeg';
}

async function prepareMediaInput(mediaUrl) {
  if (hasExplicitImageExtension(mediaUrl)) {
    return {
      media: mediaUrl,
      mimetype: guessMimeType(mediaUrl),
      fileName: fileNameFromUrl(mediaUrl),
    };
  }

  const response = await fetch(mediaUrl, {
    headers: {
      Accept: 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
      'User-Agent': 'Mozilla/5.0 (compatible; descontos.bot/evolution-adapter)',
    },
  });
  if (!response.ok) {
    throw new Error(`Falha ao baixar mídia da oferta: HTTP ${response.status}`);
  }
  const contentType = normalizeImageContentType(response.headers.get('content-type'));
  const buffer = Buffer.from(await response.arrayBuffer());
  return {
    media: buffer.toString('base64'),
    mimetype: contentType,
    fileName: `offer.${extensionFromMimeType(contentType)}`,
  };
}

function hasExplicitImageExtension(url) {
  const clean = String(url || '').split('?')[0].toLowerCase();
  return clean.endsWith('.jpg') || clean.endsWith('.jpeg') || clean.endsWith('.png') || clean.endsWith('.webp');
}

function normalizeImageContentType(value) {
  const contentType = String(value || '').split(';')[0].trim().toLowerCase();
  if (contentType === 'image/png') return 'image/png';
  if (contentType === 'image/webp') return 'image/webp';
  return 'image/jpeg';
}

function extensionFromMimeType(mimetype) {
  if (mimetype === 'image/png') return 'png';
  if (mimetype === 'image/webp') return 'webp';
  return 'jpg';
}

function fileNameFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const last = pathname.split('/').filter(Boolean).at(-1);
    return last || 'offer.jpg';
  } catch {
    return 'offer.jpg';
  }
}
