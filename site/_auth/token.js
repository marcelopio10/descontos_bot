/**
 * Token de sessão assinado para o site privado do descontos.bot.
 *
 * Stateless, sem banco: o cookie carrega `base64url(payload).base64url(hmac)`.
 * Assinatura HMAC-SHA256 via Web Crypto, compatível com o Edge runtime da Vercel
 * (middleware) e com o runtime Node das funções `site/api/*`.
 *
 * Nada aqui depende de segredo embutido — o secret vem sempre de
 * `SITE_AUTH_SECRET` (env), nunca do código.
 */

export const COOKIE_NAME = 'descontos_bot_session';
export const SESSION_SCOPE = 'site-private';

const enc = new TextEncoder();
const dec = new TextDecoder();

function bytesToB64url(bytes) {
  let bin = '';
  for (let i = 0; i < bytes.length; i++) {
    bin += String.fromCharCode(bytes[i]);
  }
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function b64urlToBytes(value) {
  let s = value.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    bytes[i] = bin.charCodeAt(i);
  }
  return bytes;
}

function bytesToHex(bytes) {
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, '0');
  }
  return out;
}

async function hmacSha256(message, secret) {
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return new Uint8Array(sig);
}

// Comparação de tempo constante para evitar timing attacks na assinatura/hash.
function timingSafeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export async function signToken(payload, secret) {
  const body = bytesToB64url(enc.encode(JSON.stringify(payload)));
  const sig = bytesToB64url(await hmacSha256(body, secret));
  return `${body}.${sig}`;
}

/**
 * Retorna o payload se o token for válido, íntegro e não expirado; senão null.
 */
export async function verifyToken(token, secret) {
  if (!token || typeof token !== 'string' || !secret) return null;
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const [body, sig] = parts;

  const expected = bytesToB64url(await hmacSha256(body, secret));
  if (!timingSafeEqual(sig, expected)) return null;

  let payload;
  try {
    payload = JSON.parse(dec.decode(b64urlToBytes(body)));
  } catch {
    return null;
  }
  if (!payload || typeof payload.exp !== 'number') return null;
  if (payload.scope !== SESSION_SCOPE) return null;
  if (Date.now() >= payload.exp * 1000) return null;
  return payload;
}

export async function createSessionToken(sub, secret, ttlSeconds) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub,
    iat: now,
    exp: now + ttlSeconds,
    scope: SESSION_SCOPE,
  };
  return signToken(payload, secret);
}

/**
 * Hash de senha do operador: HMAC-SHA256(senha, SITE_AUTH_SECRET) em hex.
 * Liga o hash ao secret (sem rainbow table) e dispensa dependência de bcrypt
 * no Edge runtime. É o mesmo valor guardado em SITE_AUTH_PASSWORD_HASH.
 */
export async function hashPassword(password, secret) {
  return bytesToHex(await hmacSha256(password, secret));
}

export async function verifyPassword(password, secret, expectedHashHex) {
  if (!expectedHashHex) return false;
  const actual = await hashPassword(password, secret);
  return timingSafeEqual(actual, String(expectedHashHex).toLowerCase());
}
