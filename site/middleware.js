/**
 * Edge Middleware — protege as rotas privadas do site descontos.bot.
 *
 * Estratégia fail-closed por allowlist de matcher: o middleware SÓ executa nas
 * rotas privadas declaradas em `config.matcher`. Tudo que não estiver no matcher
 * (home, oferta, links, sobre, disclosure, /r, /api/click, assets, offers.json,
 * links.json, og.png) nunca passa por aqui e continua público por padrão.
 *
 * Rotas privadas:
 *   - páginas:   /dashboard, /inteligencia (com e sem .html)
 *   - dados:     /affiliate-summary.json, /market-intel.json
 *   - prefixos:  /admin, /analise, /analysis, /ops, /private (uso futuro)
 *
 * Sem sessão válida: páginas redirecionam para /login?next=<rota>; recursos de
 * dados (JSON) recebem 401, evitando vazar comissão/inteligência por URL direta.
 */

import { next } from '@vercel/edge';
import { verifyToken, COOKIE_NAME } from './_auth/token.js';
import { readCookie } from './_auth/cookie.js';

export const config = {
  matcher: [
    '/dashboard',
    '/dashboard.html',
    '/inteligencia',
    '/inteligencia.html',
    '/affiliate-summary.json',
    '/market-intel.json',
    '/admin/:path*',
    '/analise/:path*',
    '/analysis/:path*',
    '/ops/:path*',
    '/private/:path*',
  ],
};

function isDataRequest(pathname) {
  return pathname.endsWith('.json');
}

export default async function middleware(request) {
  const secret = process.env.SITE_AUTH_SECRET;
  const url = new URL(request.url);
  const pathname = url.pathname;

  // Sem secret configurado: falha fechada para não servir rota privada por engano.
  let payload = null;
  if (secret) {
    const token = readCookie(request, COOKIE_NAME);
    payload = await verifyToken(token, secret);
  }

  if (payload) {
    return next();
  }

  if (isDataRequest(pathname)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  }

  const loginUrl = new URL('/login', request.url);
  // `next` é sempre o pathname interno (começa com /), seguro contra open redirect.
  loginUrl.searchParams.set('next', pathname + url.search);
  return Response.redirect(loginUrl, 307);
}
