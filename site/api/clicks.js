/**
 * GET /api/clicks
 *
 * Retorna dados agregados de cliques para o dashboard.
 * Lê eventos do Vercel KV (lista `clicks:events`).
 *
 * Response:
 * {
 *   "clicks_by_channel": [{ "channel": "whatsapp", "count": 42 }, ...],
 *   "top_offers": [{ "slug": "...", "title": "...", "count": 12 }, ...],
 *   "total_clicks_7d": 156,
 *   "total_offers_7d": 986,
 *   "generated_at": "2026-05-26T20:08:09Z"
 * }
 *
 * Depende de `@vercel/kv` (disponível no runtime da Vercel com KV habilitado).
 * Compatível com a estrutura de escrita do endpoint /api/click (T7 — Didi).
 */

// Intervalo de 7 dias em ms
var SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

export default async function handler(req) {
  if (req.method !== 'GET') {
    return new Response(JSON.stringify({ error: 'Method not allowed' }), {
      status: 405,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    // Verifica se o KV está disponível
    if (typeof kv === 'undefined') {
      return fallbackResponse();
    }

    var now = Date.now();
    var cutoff = now - SEVEN_DAYS_MS;

    // Lê todos os eventos da lista `clicks:events`
    var rawEvents = await kv.lrange('clicks:events', 0, -1);
    if (!rawEvents || rawEvents.length === 0) {
      return emptyResponse();
    }

    var events = [];
    for (var i = 0; i < rawEvents.length; i++) {
      try {
        var evt = typeof rawEvents[i] === 'string' ? JSON.parse(rawEvents[i]) : rawEvents[i];
        if (evt.clicked_at) {
          var clickedAt = new Date(evt.clicked_at).getTime();
          if (clickedAt >= cutoff) {
            events.push(evt);
          }
        }
      } catch (_) {
        // ignora eventos malformados
      }
    }

    // Agrega por canal
    var channelMap = {};
    for (var j = 0; j < events.length; j++) {
      var ch = events[j].utm_source || 'direct';
      channelMap[ch] = (channelMap[ch] || 0) + 1;
    }
    var clicksByChannel = Object.keys(channelMap)
      .map(function (key) {
        return { channel: key, count: channelMap[key] };
      })
      .sort(function (a, b) { return b.count - a.count; });

    // Top 10 ofertas
    var offerMap = {};
    for (var k = 0; k < events.length; k++) {
      var s = events[k].slug;
      if (!s) continue;
      if (!offerMap[s]) {
        offerMap[s] = { slug: s, title: events[k].offer_title || s, count: 0 };
      }
      offerMap[s].count += 1;
    }
    var topOffers = Object.keys(offerMap)
      .map(function (key) { return offerMap[key]; })
      .sort(function (a, b) { return b.count - a.count; })
      .slice(0, 10);

    return new Response(
      JSON.stringify({
        clicks_by_channel: clicksByChannel,
        top_offers: topOffers,
        total_clicks_7d: events.length,
        total_offers_7d: null, // preenchido pelo frontend via offers.json
        generated_at: new Date().toISOString(),
      }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: 'Internal error', detail: err.message }),
      {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}

function emptyResponse() {
  return new Response(
    JSON.stringify({
      clicks_by_channel: [],
      top_offers: [],
      total_clicks_7d: 0,
      total_offers_7d: null,
      generated_at: new Date().toISOString(),
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    }
  );
}

function fallbackResponse() {
  return new Response(
    JSON.stringify({
      clicks_by_channel: [],
      top_offers: [],
      total_clicks_7d: 0,
      total_offers_7d: null,
      generated_at: new Date().toISOString(),
      notice: 'Vercel KV não configurado. Configure a integração KV no dashboard da Vercel.',
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    }
  );
}
