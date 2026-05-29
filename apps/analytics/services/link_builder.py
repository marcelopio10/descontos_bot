from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


BRIDGE_MARKETPLACES = {'amazon'}
ML_MARKETPLACE_CODE = 'mercadolivre'
REFERRAL_HUB_PATH = '/links'
REFERRAL_DEFAULT_EVERY_N = 5

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
    """
    if offer.marketplace.code in BRIDGE_MARKETPLACES:
        if not offer.slug:
            raise ValueError('Oferta Amazon sem slug não pode usar bridge.')
        return offer.bridge_url

    base_url = offer.affiliate_link
    if channel_code and offer.marketplace.code == ML_MARKETPLACE_CODE:
        subid = build_ml_subid(channel_code, offer.id)
        return _append_utm_params(base_url, **{ML_SUBID_PARAM: subid})
    return base_url


def build_ml_subid(channel_code: str, offer_id: int) -> str:
    """Gera SubID Mercado Livre no padrão dbot_{canal}_{offer_id}."""
    return f'dbot_{channel_code}_{offer_id}'


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
