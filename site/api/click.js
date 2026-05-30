import { kv } from '@vercel/kv';

const EVENTS_KEY = 'clicks:events';

export default async function handler(req) {
  if (req.method !== 'GET') {
    return new Response(null, { status: 405 });
  }

  const queryString = req.url.split('?')[1] || '';
  const searchParams = new URLSearchParams(queryString);
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
    user_agent: req.headers.get('user-agent') || '',
    ip_hash: hash_ip(get_client_ip(req)),
    offer_title: '',
  };

  try {
    await kv.rpush(EVENTS_KEY, JSON.stringify(event));
  } catch {
    // falha silenciosa — não bloqueia o redirect
  }

  return new Response(null, { status: 204 });
}

function get_client_ip(req) {
  return (
    req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    req.headers.get('x-real-ip') ||
    'unknown'
  );
}

function hash_ip(ip) {
  // hash simples para privacidade — SHA-256 truncado
  let hash = 0;
  const str = `descontos.bot:${ip}:click`;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(8, '0');
}
