/**
 * POST /api/logout
 *
 * Encerra a sessão limpando o cookie de sessão. Idempotente.
 */

import { buildClearCookie, isSecureRequest } from '../_auth/cookie.js';

function handle(request) {
  const cookie = buildClearCookie(isSecureRequest(request));
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      'Set-Cookie': cookie,
    },
  });
}

export const POST = handle;
export const GET = handle;
