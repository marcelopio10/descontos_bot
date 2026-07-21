# Política de Links por Marketplace

> Documento normativo. Regula como links de oferta são construídos antes de chegar ao usuário em qualquer canal (WhatsApp, Telegram, Instagram, site, bio).

## Princípio

**Sempre usar o link do marketplace.** Não interpor domínio próprio entre o usuário e o marketplace, exceto quando o programa de afiliados do marketplace exigir.

Hoje só a Amazon exige interposição (compliance Amazon TOS, diversidade de origem de cliques — não pode ser só canal fechado). Por isso links Amazon passam pelo bridge `/r?slug=...`. Demais marketplaces vão diretos.

## Regra por marketplace

| Marketplace | Destino do link | Por quê |
|---|---|---|
| Amazon (`amazon`) | `https://descontos.bot/r?slug=<slug>&utm_*` | Compliance Amazon TOS exige diversidade de origem. Tracking via `ClickEvent` é efeito colateral. |
| Mercado Livre (`mercadolivre`) | `https://meli.la/...?utm_*` (link direto + SubID nativo ML) | Política "sempre usar link do marketplace". Tracking via painel oficial Mercado Livre Afiliados (SubID). |
| Shopee (`shopee`) | Link direto (`offer.affiliate_link`); ou short link Shopee com SubID de canal quando `SHOPEE_AFFILIATE_ENABLED=true` (default hoje: desligado) | Política "sempre usar link do marketplace". Tracking via SubID nativo no Conversion Report oficial da Shopee (Tarefa 4.1). |

A constante que controla a regra fica em `apps/analytics/services/link_builder.py`:

```python
BRIDGE_MARKETPLACES = {'amazon'}
```

Para incluir novo marketplace no bridge (caso compliance exija), adicione o `Marketplace.code` ao set. Caso contrário, novo marketplace já vai direto por default.

## Como rastrear cliques

### Amazon
- Cliente abre `/r?slug=...&utm_*`
- `site/r.html` dispara `sendBeacon('/api/click', ...)` com os UTMs
- `/api/click` (Vercel Function) grava em Vercel KV
- `python3 manage.py fetch_clicks` sincroniza KV → `ClickEvent` no Django
- Dashboard `/dashboard.html` consome `/api/clicks`

### Mercado Livre
- Cliente abre `https://meli.la/...?utm_*`
- ML faz o redirect interno e registra o clique no painel oficial **Mercado Livre Afiliados > Relatórios**
- UTMs Google-style (`utm_source` etc.) **não** são interpretados pelo painel ML — quem entrega a granularidade por canal é o **SubID nativo ML**, anexado pelo Bloco A.6 (pendente)
- Para consolidar com Amazon: ver Bloco G+ (opcional) ou reconciliação manual semanal

### Shopee
- Cliente abre o link de afiliado Shopee (`offer.affiliate_link`, sem passar pelo `/r`)
- Com `SHOPEE_AFFILIATE_ENABLED=true` (default hoje: **desligado** — em produção o comportamento é idêntico ao link direto, sem chamar a API Shopee), `resolve_destination_url()` gera um short link via **Shopee Affiliate Open API** (`generateShortLink`), gravando o canal no **SubID nativo** (`subId2`) — ver `apps/marketplaces/services/shopee_link_generator.py`
- Shopee registra a conversão com o SubID no próprio **Conversion Report** do Shopee Affiliate Program
- A ingestão (`ingest_affiliate_shopee`, `apps/analytics/services/affiliate_parsers/shopee.py`) lê `subId2` e reconstrói `AffiliateConversion.social_channel` — ver `docs/AFFILIATE_REPORTS_INGESTION.md` (seção Shopee) para o fluxo completo
- Salvaguardas de produção (Tarefa 4.1): client dedicado com timeout curto (5s) e 1 retry (não os defaults globais de até ~60s), e qualquer falha da API cai no link direto (`offer.affiliate_link`) via `log.warning`, nunca bloqueia o envio

## Mapa SubID Mercado Livre

Padrão: `dbot_{canal_curto}_{offer_id}`

Mecanismo: query string Marketing Toolbox ML (`?matt_word=<subid>`) anexada ao link `meli.la/...`. Implementado em `apps/analytics/services/link_builder.py` via constante `ML_SUBID_PARAM`.

Mapeamento canal → SubID (baseado nos canais ativos do seed):

| `SocialChannel.code` | `channel_code` curto | SubID gerado |
|---|---|---|
| `whatsapp_main` | `wa_main` | `dbot_wa_main_<offer_id>` |
| `whatsapp_principal` | `wa_principal` | `dbot_wa_principal_<offer_id>` |
| `telegram_main` | `tg_main` | `dbot_tg_main_<offer_id>` |
| `telegram_homolog` | `tg_homolog` | `dbot_tg_homolog_<offer_id>` |
| Instagram story | `ig_story` | `dbot_ig_story_<offer_id>` |
| Instagram feed | `ig_feed` | `dbot_ig_feed_<offer_id>` |
| Instagram carousel | `ig_carousel` | `dbot_ig_carousel_<offer_id>` |
| Instagram reel | `ig_reel` | `dbot_ig_reel_<offer_id>` |
| Instagram bio | `ig_bio` | `dbot_ig_bio_<offer_id>` |

A função `_short_channel_code()` em `link_builder.py` mapeia prefixo `whatsapp_` → `wa_` e `telegram_` → `tg_` automaticamente. Canais novos seguem o padrão sem precisar tocar o código.

**Validação obrigatória pelo PO após primeiro envio real:** abrir painel Mercado Livre Afiliados > Relatórios e confirmar que SubIDs como `dbot_wa_main_4061` aparecem segmentados. Se o painel não interpretar `matt_word`, alterar `ML_SUBID_PARAM` para o parâmetro correto (alternativas conhecidas: `label`, `sub_id`, `tracking_id`).

## Decisão RESTR-03 — click tracking próprio não será expandido

Registro da decisão (Sprint 4, Tarefa 4.3, `docs/PLANO_REFATORACAO_POS_DIAGNOSTICO_2026-07-18.md`):

- O `ClickEvent`/`/api/click` (ver seção "Amazon" acima) é **best-effort e específico da Amazon**, mantido por exigência de compliance Amazon TOS (o bridge `/r` já precisa existir para diversidade de origem; o tracking de clique é só um efeito colateral aproveitando esse redirect).
- Essa interceptação de clique **não será expandida para outros marketplaces** — nem Mercado Livre, nem Shopee. Interpor domínio próprio no link de um marketplace que não exige (violando o Princípio no topo deste documento) só para ganhar tracking é desencorajado.
- ML e Shopee já têm mecanismos **nativos e melhores** para medir por canal: SubID. ML usa `matt_word` (Marketing Toolbox, ver "Mapa SubID Mercado Livre" acima); Shopee usa `subId2` no Conversion Report oficial (ver seção "Shopee" acima e Tarefa 4.1). Ambos evitam o redirect extra e não dependem de o cliente não bloquear `sendBeacon`/JS.
- Para Amazon, na ausência de SubID nativo equivalente, o cruzamento por canal continua sendo **correlação temporal** (envios × comissão na mesma semana, não atribuição exata por clique) — ver `apps/analytics/services/operational_metrics.py::deliveries_vs_commission_by_marketplace_week` (Tarefa 4.2) e o painel operacional (`site/painel-operacional.json`).

## Onde está implementado

| Função | Arquivo | Uso |
|---|---|---|
| `resolve_destination_url(offer)` | `apps/analytics/services/link_builder.py` | Função central. Retorna URL base por marketplace, sem UTMs |
| `build_tracked_url(offer, channel)` | mesmo arquivo | WhatsApp/Telegram — anexa UTMs por canal |
| `build_instagram_tracked_url(offer, medium, content)` | mesmo arquivo | Instagram (story/feed/carousel/reel/bio) — anexa UTMs Instagram |

Call sites:
- `apps/curation/services/message_builder.py` — mensagens WhatsApp/Telegram
- `apps/social_posts/services/bio_link_publisher.py` — links da bio Instagram
- `apps/social_posts/services/post_generator.py` — `sticker_target_url` em posts
- `apps/social_posts/services/image_renderer.py` — fallback de URL em renderização

## O que NÃO fazer

- **Não passar Mercado Livre (ou outro marketplace fora do `BRIDGE_MARKETPLACES`) pelo `/r`** — viola o princípio e desperdiça um redirect.
- **Não bypassar o `/r` para Amazon** — viola compliance Amazon TOS e quebra o rastreamento de cliques no nosso dashboard.
- **Não usar `SocialChannel.link_strategy` para decidir destino** — após esta política, o campo é informativo; quem decide é o marketplace.
- **Não construir URL de oferta fora de `link_builder.py`** — todas as inserções de URL em mensagens, posts e bio devem passar pelas três funções acima.
- **Não expandir o `ClickEvent`/`/api/click` para ML ou Shopee** — decisão RESTR-03 (ver seção acima); esses marketplaces já têm SubID nativo.

## Validação manual

```bash
python3 manage.py shell -c "
from apps.analytics.services.link_builder import resolve_destination_url, build_tracked_url, build_instagram_tracked_url
from apps.offers.models import Offer
from apps.distribution.models import SocialChannel

o_amz = Offer.objects.filter(marketplace__code='amazon', slug__isnull=False).exclude(slug='').first()
o_ml  = Offer.objects.filter(marketplace__code='mercadolivre').first()
o_shp = Offer.objects.filter(marketplace__code='shopee').first()
ch_wa = SocialChannel.objects.filter(channel_type__startswith='whatsapp').first()

print('amazon →', resolve_destination_url(o_amz))   # /r?slug=...
print('ml →',     resolve_destination_url(o_ml))     # https://meli.la/...
print('shopee →', resolve_destination_url(o_shp))    # link direto (SHOPEE_AFFILIATE_ENABLED off por padrão)
print('amz+wa →', build_tracked_url(o_amz, ch_wa))   # /r?slug=...&utm_source=whatsapp...
print('ml+wa →',  build_tracked_url(o_ml, ch_wa))    # https://meli.la/...?utm_source=whatsapp...
print('shopee+wa →', build_tracked_url(o_shp, ch_wa))  # idem link direto + utm_source=whatsapp (sem SubID Shopee enquanto a flag estiver off)
print('amz/ig →', build_instagram_tracked_url(o_amz, 'story'))  # /r?slug=...&utm_source=instagram...
print('ml/ig →',  build_instagram_tracked_url(o_ml, 'story'))    # https://meli.la/...?utm_source=instagram...
"
```
