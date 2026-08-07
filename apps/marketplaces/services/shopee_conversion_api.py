"""Read-only adapter for Shopee Affiliate conversion reports."""

from datetime import datetime, timezone
import json

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateClient


def _epoch(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def fetch_conversion_report(
    start: datetime,
    end: datetime,
    *,
    limit: int = 100,
    scroll_id: str | None = None,
    client: ShopeeAffiliateClient | None = None,
) -> dict:
    """Consulta relatório oficial sem persistir ou publicar nada.

    API atual aceita argumentos literais `Int64`; não usar interpolação de texto
    externa: datas são convertidas para epoch e `scroll_id` é JSON-quoted.
    """
    if limit < 1 or limit > 1000:
        raise ValueError('limit deve estar entre 1 e 1000.')
    start_epoch = _epoch(start)
    end_epoch = _epoch(end)
    if end_epoch <= start_epoch:
        raise ValueError('end precisa ser posterior a start.')

    fields = """
      nodes {
        clickTime purchaseTime conversionId conversionStatus
        grossCommission estimatedTotalCommission totalCommission netCommission
        utmContent referrer
        orders {
          orderId orderStatus
          items {
            shopId itemId itemName itemPrice actualAmount refundAmount qty
            itemCommission itemTotalCommission attributionType channelType
          }
        }
      }
      pageInfo { hasNextPage scrollId }
    """.strip()
    scroll_clause = f', scrollId: {json.dumps(scroll_id)}' if scroll_id else ''
    query = (
        '{ conversionReport('
        f'purchaseTimeStart: {start_epoch}, '
        f'purchaseTimeEnd: {end_epoch}, '
        f'limit: {limit}{scroll_clause}'
        f') {{ {fields} }} }}'
    )
    return (client or ShopeeAffiliateClient()).execute(query)


def normalize_conversion_report(payload: dict) -> list[dict]:
    """Normaliza linhas por item, sem inventar canal.

    O schema homologado expõe `utmContent`/`channelType`, mas não expõe SubIDs
    nativos. Logo `channel` permanece None até existir evidência explícita.
    """
    report = payload.get('conversionReport') or {}
    rows: list[dict] = []
    for conversion in report.get('nodes') or []:
        conversion_id = str(conversion.get('conversionId') or '')
        for order in conversion.get('orders') or []:
            order_id = str(order.get('orderId') or '')
            for item in order.get('items') or []:
                item_id = str(item.get('itemId') or '')
                shop_id = str(item.get('shopId') or '')
                if not item_id:
                    continue
                rows.append({
                    'conversion_id': conversion_id,
                    'order_id': order_id,
                    'item_id': item_id,
                    'shop_id': shop_id,
                    'external_ref': f'{item_id}:{shop_id}' if shop_id else item_id,
                    'product_title': str(item.get('itemName') or ''),
                    'purchase_time': conversion.get('purchaseTime'),
                    'status': str(conversion.get('conversionStatus') or order.get('orderStatus') or ''),
                    'quantity': int(item.get('qty') or 1),
                    'revenue_brl': str(item.get('actualAmount') or '0'),
                    'commission_brl': str(
                        item.get('itemTotalCommission')
                        or conversion.get('netCommission')
                        or conversion.get('totalCommission')
                        or '0'
                    ),
                    'channel': None,
                    'utm_content': str(conversion.get('utmContent') or ''),
                    'attribution_type': str(item.get('attributionType') or ''),
                })
    return rows
