/**
 * Helpers de cookie de sessão. Mantém os atributos de segurança num único lugar
 * para login, logout e middleware nunca divergirem.
 */

import { COOKIE_NAME } from './token.js';

// Secure só quando a requisição é HTTPS, para não quebrar `vercel dev` em http local.
export function isSecureRequest(request) {
  const proto = request.headers.get('x-forwarded-proto');
  if (proto) return proto.split(',')[0].trim() === 'https';
  try {
    return new URL(request.url).protocol === 'https:';
  } catch {
    return false;
  }
}

export function buildSessionCookie(token, ttlSeconds, secure) {
  const attrs = [
    `${COOKIE_NAME}=${token}`,
    'HttpOnly',
    'SameSite=Lax',
    'Path=/',
    `Max-Age=${ttlSeconds}`,
  ];
  if (secure) attrs.push('Secure');
  return attrs.join('; ');
}

export function buildClearCookie(secure) {
  const attrs = [`${COOKIE_NAME}=`, 'HttpOnly', 'SameSite=Lax', 'Path=/', 'Max-Age=0'];
  if (secure) attrs.push('Secure');
  return attrs.join('; ');
}

export function readCookie(request, name) {
  const header = request.headers.get('cookie') || '';
  for (const part of header.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    if (part.slice(0, idx).trim() === name) {
      return part.slice(idx + 1).trim();
    }
  }
  return null;
}
