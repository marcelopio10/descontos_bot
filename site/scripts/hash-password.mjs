/**
 * Gera o SITE_AUTH_PASSWORD_HASH a partir da senha do operador.
 *
 * O hash é HMAC-SHA256(senha, SITE_AUTH_SECRET) em hex — o mesmo valor que
 * /api/login recomputa para validar. A senha pura nunca é armazenada.
 *
 * Uso:
 *   SITE_AUTH_SECRET='seu-secret-forte' node site/scripts/hash-password.mjs 'minha-senha'
 *
 * Cole a saída em SITE_AUTH_PASSWORD_HASH (.env local e Environment Variables do Vercel).
 * Requer Node 18+ (crypto.subtle / btoa globais).
 */

import { hashPassword } from '../_auth/token.js';

const password = process.argv[2];
const secret = process.env.SITE_AUTH_SECRET;

if (!password || !secret) {
  console.error(
    "Uso: SITE_AUTH_SECRET='...' node site/scripts/hash-password.mjs '<senha>'"
  );
  process.exit(1);
}

const hash = await hashPassword(password, secret);
console.log(hash);
