export class RouterRequestError extends Error {
  constructor() {
    super('Falha ao enfileirar oferta no roteador');
    this.name = 'RouterRequestError';
    this.statusCode = 502;
  }
}

export async function enqueueOffer(config, groupMap, destination, offer) {
  validateOffer(offer);
  const destinationAlias = requireSymbolicDestination(destination);
  const target = resolveMappedTarget(groupMap, destinationAlias);
  const routerAlias = requireRouterAlias(target.router_alias);
  const payload = {
    type: 'offer',
    destination: routerAlias,
    idempotency_key: offer.idempotencyKey,
    text: offer.text,
  };
  if (offer.mediaUrl) payload.media_url = offer.mediaUrl;

  try {
    const response = await fetch(`${requiredBaseUrl(config)}/v1/outbound`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${requiredToken(config)}`,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(config.routerTimeoutMs || 5000),
    });
    if (!response.ok) throw new RouterRequestError();
    return await response.json();
  } catch (error) {
    if (error instanceof RouterRequestError) throw error;
    throw new RouterRequestError();
  }
}

function requireSymbolicDestination(destination) {
  if (typeof destination !== 'string' || !destination.trim() || destination.includes('@')) {
    throw new Error('Destino deve usar alias simbólico');
  }
  return destination.trim();
}

function requireRouterAlias(value) {
  if (typeof value !== 'string' || !/^[a-z][a-z0-9_-]{0,63}$/.test(value)) {
    throw new Error('Destino mapeado exige router_alias opaco');
  }
  return value;
}

function resolveMappedTarget(groupMap, destination) {
  const target = groupMap.resolveTarget(destination);
  const isMapped = groupMap.listAllowed([target.jid]).some((item) => item.jid === target.jid);
  if (!isMapped) throw new Error('Destino não autorizado pelo mapa local');
  return target;
}

function validateOffer(offer) {
  if (!offer || typeof offer !== 'object') throw new Error('Oferta inválida');
  if (typeof offer.idempotencyKey !== 'string' || !offer.idempotencyKey.trim()) {
    throw new Error('idempotency key obrigatória');
  }
  if (typeof offer.text !== 'string' || !offer.text.trim()) throw new Error('Texto da oferta é obrigatório');
  if (offer.mediaUrl !== undefined && (typeof offer.mediaUrl !== 'string' || !offer.mediaUrl.trim())) {
    throw new Error('Mídia da oferta deve ser uma URL não vazia');
  }
}

function requiredBaseUrl(config) {
  const value = config.routerBaseUrl?.trim().replace(/\/$/, '');
  if (!value) throw new RouterRequestError();
  return value;
}

function requiredToken(config) {
  const value = config.routerToken?.trim();
  if (!value) throw new RouterRequestError();
  return value;
}
