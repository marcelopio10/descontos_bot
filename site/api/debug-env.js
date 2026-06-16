/**
 * GET /api/debug-env
 * TEMPORARY debug endpoint — remove after verification.
 * Returns lengths of auth env vars (not values).
 */
export async function GET() {
  const user = process.env.SITE_AUTH_USER || '';
  const hash = process.env.SITE_AUTH_PASSWORD_HASH || '';
  const secret = process.env.SITE_AUTH_SECRET || '';
  return new Response(JSON.stringify({
    user_len: user.length,
    user_first: user.substring(0, 3),
    hash_len: hash.length,
    hash_first4: hash.substring(0, 4),
    hash_last4: hash.substring(hash.length - 4),
    secret_len: secret.length,
    secret_first4: secret.substring(0, 4),
    secret_last4: secret.substring(secret.length - 4),
    computed_test: null  // placeholder
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
  });
}

/**
 * POST /api/debug-env
 * Computes hash of given password for verification.
 */
export async function POST(request) {
  const { hashPassword } = await import('../_auth/token.js');
  const secret = process.env.SITE_AUTH_SECRET || '';
  let password = '';
  try {
    const body = await request.json();
    password = body.password || '';
  } catch {}
  const h = password ? await hashPassword(password, secret) : 'no_password';
  return new Response(JSON.stringify({ computed_hash: h, hash_len: h.length }), {
    status: 200,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
  });
}
