import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

from apps.distribution.models import SocialChannel
from apps.marketplaces.services.shopee_affiliate_client import (
    ShopeeAffiliateClient,
    ShopeeAffiliateError,
)
from apps.marketplaces.services.shopee_link_generator import resolve_affiliate_link
from apps.offers.models import Offer


log = logging.getLogger('apps.analytics.link_builder')

BRIDGE_MARKETPLACES = {'amazon'}
ML_MARKETPLACE_CODE = 'mercadolivre'
SHOPEE_MARKETPLACE_CODE = 'shopee'
REFERRAL_HUB_PATH = '/links'
REFERRAL_DEFAULT_EVERY_N = 5

# Client dedicado a esta call site: timeout/retries CURTOS, diferentes do
# default global (SHOPEE_AFFILIATE_TIMEOUT_SECONDS=20/MAX_RETRIES=3, que dariam
# até ~60s de latência). Protege o loop de envio de produção (run_bot/
# publish_telegram) de travar numa falha externa da Shopee.
SHOPEE_TRACKED_LINK_TIMEOUT_SECONDS = 5
SHOPEE_TRACKED_LINK_MAX_RETRIES = 1

# Parâmetro Marketing Toolbox do Mercado Livre que aparece nos relatórios de
# afiliado por SubID. Validar no painel oficial ML após o primeiro envio real.
ML_SUBID_PARAM = 'matt_word'

_CHANNEL_PREFIX_SHORT = {
    'whatsapp': 'wa',
    'whatsapp_group': 'wa',
    'whatsapp_channel': 'wa',
    'telegram_channel': 'tg',
}


def resolve_destination_url(offer: Offer, channel_code: str | None = None) -> str:
    """Resolve a URL base por marketplace, sem UTMs.

    Amazon usa bridge (/r?slug=) por compliance Amazon TOS — exige diversidade
    de origem de cliques, não pode ser só canal fechado. Demais marketplaces
    usam o link de afiliado direto, respeitando a política de "sempre usar
    link do marketplace".

    Para Mercado Livre, quando `channel_code` é informado, anexa SubID nativo
    (matt_word) para segmentação no painel oficial ML Afiliados.

    Para Shopee, quando `channel_code` é informado e
    `settings.SHOPEE_AFFILIATE_ENABLED` está ligado, tenta gerar um short
    link com subId de canal via Shopee Affiliate API. Com a flag desligada
    (default hoje em produção) ou em qualquer falha da API, cai no link de
    afiliado padrão (`offer.affiliate_link`) sem propagar exceção — ver
    `_resolve_shopee_tracked_url`.
    """
    if offer.marketplace.code in BRIDGE_MARKETPLACES:
        if not offer.slug:
            raise ValueError('Oferta Amazon sem slug não pode usar bridge.')
        return offer.bridge_url

    base_url = offer.affiliate_link
    if channel_code and offer.marketplace.code == ML_MARKETPLACE_CODE:
        subid = build_ml_subid(channel_code, offer.id)
        return _append_utm_params(base_url, **{ML_SUBID_PARAM: subid})
    if channel_code and offer.marketplace.code == SHOPEE_MARKETPLACE_CODE:
        shopee_url = _resolve_shopee_tracked_url(offer, channel_code)
        if shopee_url:
            return shopee_url
    return base_url


def build_ml_subid(channel_code: str, offer_id: int) -> str:
    """Gera SubID Mercado Livre no padrão dbot_{canal}_{offer_id}."""
    return f'dbot_{channel_code}_{offer_id}'


def _resolve_shopee_tracked_url(offer: Offer, channel_code: str) -> str | None:
    """Gera o link Shopee com subId de canal, se `SHOPEE_AFFILIATE_ENABLED`.

    Gate por `settings.SHOPEE_AFFILIATE_ENABLED` (default off, é o estado
    real de produção hoje) — desligado, retorna None imediatamente sem
    tentar nada, e o chamador cai no fallback `offer.affiliate_link`
    (comportamento de hoje, inalterado).

    Ligado, usa um `ShopeeAffiliateClient` com timeout/retries curtos e
    dedicados a esta call site (ver `SHOPEE_TRACKED_LINK_*`), para nunca
    atrasar o envio em produção além de poucos segundos mesmo se a Shopee
    estiver fora do ar. `resolve_affiliate_link` recebe `productLink` (não
    `offerLink`) para forçar a geração do short link COM subIds em vez de
    reaproveitar um link sem tracking de canal.

    Qualquer falha (config ausente/`ShopeeConfigError`, erro controlado da
    API/`ShopeeAffiliateError`, ou qualquer outra exceção inesperada — rede
    de segurança) só gera um `log.warning`: é degradação aceitável de
    atribuição, nunca deve bloquear ou atrasar o envio da oferta em si.
    """
    if not getattr(settings, 'SHOPEE_AFFILIATE_ENABLED', False):
        return None

    client = ShopeeAffiliateClient(
        timeout=SHOPEE_TRACKED_LINK_TIMEOUT_SECONDS,
        max_retries=SHOPEE_TRACKED_LINK_MAX_RETRIES,
    )
    try:
        return resolve_affiliate_link(
            item={'productLink': offer.product_url},
            channel_code=channel_code,
            client=client,
        )
    except ShopeeAffiliateError as exc:
        # Cobre também ShopeeConfigError (subclasse) — credenciais ausentes
        # ou erro controlado da API.
        log.warning(
            'shopee_tracked_link_fallback offer_id=%s channel_code=%s error=%s',
            offer.id, channel_code, exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — rede de segurança: nunca travar o envio.
        log.warning(
            'shopee_tracked_link_unexpected_error offer_id=%s channel_code=%s error=%s',
            offer.id, channel_code, type(exc).__name__,
        )
        return None


def build_tracked_url(offer: Offer, channel: SocialChannel) -> str:
    """Constrói URL final para canais WhatsApp/Telegram com UTMs."""
    channel_code = _short_channel_code(channel)
    base_url = resolve_destination_url(offer, channel_code=channel_code)
    utm_source, utm_medium = _utm_params_for_channel(channel)
    return _append_utm_params(
        base_url,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=f'offer_{offer.id}',
    )


def build_instagram_tracked_url(
    offer: Offer,
    medium: str,
    content: str = '',
) -> str:
    """Constrói URL final para Instagram (story/feed/carousel/reel/bio) com UTMs."""
    channel_code = f'ig_{medium}'
    base_url = resolve_destination_url(offer, channel_code=channel_code)
    params = {
        'utm_source': 'instagram',
        'utm_medium': medium,
        'utm_campaign': f'offer_{offer.id}',
    }
    if content:
        params['utm_content'] = content
    return _append_utm_params(base_url, **params)


def build_referral_hub_url(channel: SocialChannel) -> str:
    """Constrói URL do hub de aquisição (/links) com UTMs de referral por canal."""
    base = settings.PUBLIC_SITE_BASE_URL.rstrip('/')
    utm_source, _ = _utm_params_for_channel(channel)
    return _append_utm_params(
        f'{base}{REFERRAL_HUB_PATH}',
        utm_source=utm_source,
        utm_medium='referral',
        utm_content='referral_v1',
    )


def build_referral_suffix(offer: Offer, channel: SocialChannel) -> str:
    """Retorna o sufixo de referral para anexar à mensagem, ou string vazia.

    Decisão determinística baseada em `offer.id % every_n == 0` — facilita
    debug e mantém cadência previsível ao longo dos ciclos.
    """
    if not _is_referral_enabled():
        return ''
    every_n = _get_referral_every_n()
    if every_n <= 0 or offer.id % every_n != 0:
        return ''
    hub_url = build_referral_hub_url(channel)
    return (
        '\n💬 Achou útil? Compartilhe descontos.bot com quem economiza:\n'
        f'{hub_url}'
    )


def _is_referral_enabled() -> bool:
    from apps.panel.models import Setting

    try:
        value = Setting.objects.get(key='referral_enabled').value
    except Setting.DoesNotExist:
        return False
    return value.strip().lower() == 'true'


def _get_referral_every_n() -> int:
    from apps.panel.models import Setting

    try:
        raw = Setting.objects.get(key='referral_every_n').value
        return int(raw)
    except (Setting.DoesNotExist, ValueError):
        return REFERRAL_DEFAULT_EVERY_N


def _short_channel_code(channel: SocialChannel) -> str:
    """Encurta o code do SocialChannel para SubID legível no painel ML.

    Mapeia o prefixo do tipo (whatsapp/telegram) para 2 letras e remove
    redundância do nome. Ex.: whatsapp_main → wa_main, telegram_homolog → tg_homolog.
    Para tipos desconhecidos, retorna channel.code direto.
    """
    prefix = _CHANNEL_PREFIX_SHORT.get(channel.channel_type)
    if not prefix:
        return channel.code
    code = channel.code
    for full_prefix in ('whatsapp_', 'telegram_'):
        if code.startswith(full_prefix):
            return f'{prefix}_{code[len(full_prefix):]}'
    return code


def _utm_params_for_channel(channel: SocialChannel) -> tuple[str, str]:
    """Mapeia canal social para utm_source e utm_medium."""
    if channel.channel_type in ('whatsapp', 'whatsapp_group'):
        return 'whatsapp', 'group'
    if channel.channel_type in ('whatsapp_channel',):
        return 'whatsapp', 'channel'
    if channel.channel_type in ('telegram_channel',):
        return 'telegram', 'channel'
    return channel.channel_type, 'social'


def _append_utm_params(url: str, **utm_params: str) -> str:
    """Anexa parâmetros de query a uma URL preservando query string existente."""
    parts = list(urlsplit(url))
    existing = dict(parse_qsl(parts[3], keep_blank_values=True))

    for key, value in utm_params.items():
        if value:
            existing[key] = value

    parts[3] = urlencode(existing)
    return urlunsplit(parts)
