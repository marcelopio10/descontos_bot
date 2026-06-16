/**
 * POST /api/login
 *
 * Autentica o operador único do site privado (dashboard/inteligência).
 * Credenciais via env: SITE_AUTH_USER, SITE_AUTH_PASSWORD_HASH, SITE_AUTH_SECRET.
 * Em sucesso, emite cookie de sessão HttpOnly assinado por HMAC.
 *
 * Body aceito: JSON `{ "user": "...", "password": "..." }`
 * ou form-urlencoded `user=...&password=...`.
 */

import { createSessionToken, verifyPassword } from '../_auth/token.js';
import { buildSessionCookie, isSecureRequest } from '../_auth/cookie.js';

const DEFAULT_TTL_SECONDS = 28800; // 8h

function jsonResponse(body, status, extraHeaders) {
  return new Response(JSON.stringify(body), {
    status,
    headers: Object.assign(
      { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      extraHeaders || {}
    ),
  });
}

async function readCredentials(request) {
  const contentType = request.headers.get('content-type') || '';
  try {
    if (contentType.includes('application/json')) {
      const body = await request.json();
      return { user: body.user, password: body.password };
    }
    const form = await request.formData();
    return { user: form.get('user'), password: form.get('password') };
  } catch {
    return { user: undefined, password: undefined };
  }
}

export async function POST(request) {
  const expectedUser = process.env.SITE_AUTH_USER;
  const passwordHash = process.env.SITE_AUTH_PASSWORD_HASH;
  const secret = process.env.SITE_AUTH_SECRET;
  const ttl = parseInt(process.env.SITE_AUTH_SESSION_TTL_SECONDS || '', 10) || DEFAULT_TTL_SECONDS;

  // Sem configuração não há login possível — falha fechada, sem detalhar o motivo.
  if (!expectedUser || !passwordHash || !secret) {
    return jsonResponse({ error: 'Serviço de autenticação indisponível.' }, 503);
  }

  const { user, password } = await readCredentials(request);
  if (!user || !password) {
    return jsonResponse({ error: 'Usuário ou senha inválidos.' }, 401);
  }

  const userMatches = user === expectedUser;
  const passwordMatches = await verifyPassword(String(password), secret, passwordHash);
  // Sempre avalia os dois para reduzir sinal de timing; mensagem genérica.
  if (!userMatches || !passwordMatches) {
    return jsonResponse({ error: 'Usuário ou senha inválidos.' }, 401);
  }

  const token = await createSessionToken(expectedUser, secret, ttl);
  const cookie = buildSessionCookie(token, ttl, isSecureRequest(request));
  return jsonResponse({ ok: true }, 200, { 'Set-Cookie': cookie });
}
