import { kv } from '@vercel/kv';

const EVENTS_KEY = 'clicks:events';

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const slug = searchParams.get('slug');

  if (!slug) {
    return new Response(null, { status: 400 });
  }

  const event = {
    slug,
    utm_source: searchParams.get('utm_source') || '',
    utm_medium: searchParams.get('utm_medium') || '',
    utm_campaign: searchParams.get('utm_campaign') || '',
    utm_content: searchParams.get('utm_content') || '',
    clicked_at: new Date().toISOString(),
    user_agent: request.headers.get('user-agent') || '',
    ip_hash: hash_ip(get_client_ip(request)),
    offer_title: '',
  };

  try {
    await kv.rpush(EVENTS_KEY, JSON.stringify(event));
  } catch {
    // falha silenciosa — não bloqueia o redirect
  }

  return new Response(null, { status: 204 });
}

function get_client_ip(request) {
  return (
    request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    request.headers.get('x-real-ip') ||
    'unknown'
  );
}

function hash_ip(ip) {
  // hash simples para privacidade — não é criptográfico, só ofusca pra evitar PII direto
  let hash = 0;
  const str = `descontos.bot:${ip}:click`;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(8, '0');
}
