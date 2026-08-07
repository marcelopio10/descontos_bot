"""Geração de links afiliados Shopee com subIds por canal/campanha.

Prioridade (Sprint 7B.6):
1. usar `offerLink` quando a API já devolve link afiliado válido;
2. senão, gerar via `generateShortLink` a partir do `productLink`, com subIds.

SubIds (rastreamento cruzado com conversionReport):
    subId1 = descontosbot
    subId2 = canal      (whatsapp, telegram, instagram, site)
    subId3 = campanha
    subId4 = categoria
    subId5 = lote/data
"""

import logging

from apps.marketplaces.services.shopee_affiliate_client import (
    ShopeeAffiliateClient,
    ShopeeAffiliateError,
)

log = logging.getLogger('apps.marketplaces.shopee')

SUBID_OWNER = 'descontosbot'
MAX_SUBIDS = 5

GENERATE_SHORT_LINK_QUERY = """
mutation generateShortLink($input: ShortLinkInput!) {
  generateShortLink(input: $input) {
    shortLink
  }
}
""".strip()


def build_sub_ids(
    channel_code: str = 'site',
    campaign: str = '',
    category: str = '',
    batch: str = '',
) -> list[str]:
    """Monta a lista de subIds na ordem oficial (sempre 5 posições)."""
    sub_ids = [SUBID_OWNER, channel_code or 'site', campaign or '', category or '', batch or '']
    return sub_ids[:MAX_SUBIDS]


def generate_short_link(
    origin_url: str,
    sub_ids: list[str],
    client: ShopeeAffiliateClient | None = None,
) -> str:
    if not origin_url:
        raise ShopeeAffiliateError('generateShortLink exige originUrl.')
    client = client or ShopeeAffiliateClient()
    variables = {'input': {'originUrl': origin_url, 'subIds': sub_ids}}
    data = client.execute(GENERATE_SHORT_LINK_QUERY, variables)
    short_link = (data.get('generateShortLink') or {}).get('shortLink')
    if not short_link:
        raise ShopeeAffiliateError('generateShortLink não retornou shortLink.')
    return short_link


def resolve_affiliate_link(
    item: dict,
    channel_code: str = 'site',
    campaign: str = '',
    category: str = '',
    batch: str = '',
    client: ShopeeAffiliateClient | None = None,
) -> str:
    """Retorna o link afiliado oficial do item; nunca um link comum sem tracking.

    Mantém `offerLink` quando presente; caso contrário gera short link com subIds.
    Levanta erro se não houver como produzir um link rastreável (gate de publicação).
    """
    offer_link = (item.get('offerLink') or '').strip()
    if offer_link:
        return offer_link

    origin_url = (item.get('productLink') or '').strip()
    sub_ids = build_sub_ids(channel_code, campaign, category, batch)
    return generate_short_link(origin_url, sub_ids, client=client)
