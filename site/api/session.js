/**
 * GET /api/session
 *
 * Informa se a sessão atual é válida. Útil para o frontend decidir exibir
 * o botão "Sair" ou reagir à expiração sem recarregar a página.
 */

import { verifyToken, COOKIE_NAME } from '../_auth/token.js';
import { readCookie } from '../_auth/cookie.js';

export async function GET(request) {
  const secret = process.env.SITE_AUTH_SECRET;
  const token = readCookie(request, COOKIE_NAME);
  const payload = secret ? await verifyToken(token, secret) : null;

  return new Response(
    JSON.stringify({
      authenticated: Boolean(payload),
      sub: payload ? payload.sub : null,
      exp: payload ? payload.exp : null,
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    }
  );
}
