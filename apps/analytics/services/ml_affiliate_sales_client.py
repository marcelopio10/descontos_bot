"""Cliente do painel de afiliados do Mercado Livre — vendas detalhadas.

Endpoint descoberto pelo dono em 2026-08-23, capturando a chamada XHR do próprio
painel:

    GET https://www.mercadolivre.com.br/affiliate-program/api/dashboard/sales/general
        ?filter_time_range=<ISO_INICIO>--<ISO_FIM>
        &items_per_page=50
        &page=1
        &order_by=ord_date_created
        &sort=desc
        &type=GENERAL

Diferença para o relatório já suportado em `affiliate_parsers/mercadolivre.py`:
aquele é agregado por produto no período inteiro (`item_list`/`entity_id`); este
devolve **venda a venda**, com data, status e motivo de rejeição. É o que permite
separar comissão aprovada de rejeitada e marcar compra própria.

Limites verificados na sondagem de 2026-08-23:

- `items_per_page=50` funciona; `100` devolve página vazia. O teto é 50.
- `type` é ignorado — qualquer valor inválido cai em `GENERAL`.
- Não existe recorte por SubID: `type=SUBID`, `/sales/subid`, `/clicks` e
  `/metrics` devolvem 404 ou caem no mesmo GENERAL. Ou seja, o `matt_word` que o
  projeto injeta em todo link **não volta por aqui** — a atribuição por canal
  continua sem fonte oficial.
- Autentica com o mesmo `ML_COOKIE` do `.env` usado pelo scraper. Cookie vencido
  derruba esta rotina junto com a coleta.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time

from apps.analytics.services.alertas import enviar_alerta_operador
from scrapers.base import build_impersonated_session

log = logging.getLogger(__name__)

ENDPOINT = (
    'https://www.mercadolivre.com.br/affiliate-program/api/dashboard/sales/general'
)
MAX_ITEMS_PER_PAGE = 50
DEFAULT_MAX_PAGES = 40
BRT_OFFSET = '-03:00'


class MLAffiliateAuthError(RuntimeError):
    """Cookie ausente, expirado ou rejeitado pelo ML."""


class MLAffiliateFetchError(RuntimeError):
    """Falha de rede/HTTP que não é de autenticação."""


@dataclass(frozen=True)
class SaleRecord:
    """Uma venda do painel, já normalizada.

    `sale_id` é o identificador do próprio ML e é o que dá idempotência à
    ingestão — reimportar a mesma janela não duplica linha.
    """

    sale_id: str
    sale_date: date
    product_name: str
    product_link: str
    category_name: str
    store_name: str
    sale_value: float
    sale_units: int
    commission_value: float
    commission_percentage: float
    sale_type: str
    status: str
    status_detail: str

    @property
    def external_ref(self) -> str:
        """MLB extraído do link, quando o link é de produto.

        33 das 74 vendas da amostra de 2026-08-23 vinham com link de **catálogo**
        (`/p/MLB…`), que é outro espaço de identificadores e não casa com
        `Offer.external_id`. Por isso a resolução para oferta não pode depender
        só disto — ver `_resolve_offer` no parser.
        """
        return _extract_mlb(self.product_link)


def fetch_sales(
    *,
    start: date,
    end: date,
    cookie: str = '',
    max_pages: int = DEFAULT_MAX_PAGES,
    items_per_page: int = MAX_ITEMS_PER_PAGE,
    session=None,
) -> list[SaleRecord]:
    """Coleta as vendas do período, paginando até a página vazia.

    Levanta `MLAffiliateAuthError` em 401/403 (e dispara alerta ao operador,
    porque é o mesmo modo de falha que derruba a coleta do ML) e
    `MLAffiliateFetchError` em erro de rede ou HTTP inesperado.
    """
    cookie = cookie or os.environ.get('ML_COOKIE', '')
    if not cookie:
        raise MLAffiliateAuthError(
            'ML_COOKIE ausente no ambiente — sem ele o painel de afiliados não responde.'
        )

    items_per_page = min(items_per_page, MAX_ITEMS_PER_PAGE)
    session = session or build_impersonated_session('chrome124')
    headers = {
        'accept': 'application/json, text/plain, */*',
        'cookie': cookie,
        'referer': 'https://www.mercadolivre.com.br/affiliate-program/dashboard',
        'user-agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/147.0.0.0 Safari/537.36'
        ),
    }

    records: list[SaleRecord] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        params = {
            'filter_time_range': f'{_iso(start)}--{_iso(end, end_of_day=True)}',
            'items_per_page': items_per_page,
            'order_by': 'ord_date_created',
            'page': page,
            'sort': 'desc',
            'type': 'GENERAL',
        }
        try:
            resp = session.get(ENDPOINT, headers=headers, params=params, timeout=30)
        except Exception as exc:  # rede/TLS — não distingue, só reporta
            raise MLAffiliateFetchError(
                f'Falha de rede ao buscar vendas (página {page}): {exc}'
            ) from exc

        if resp.status_code in (401, 403):
            mensagem = (
                'Painel de afiliados do ML rejeitou o cookie '
                f'(HTTP {resp.status_code}) na ingestão de vendas. '
                'Renove ML_COOKIE no .env — a coleta de ofertas do ML cai junto.'
            )
            log.error(mensagem)
            enviar_alerta_operador(mensagem, categoria='ml_cookie_expirado')
            raise MLAffiliateAuthError(mensagem)
        if not resp.ok:
            raise MLAffiliateFetchError(
                f'HTTP {resp.status_code} ao buscar vendas (página {page}).'
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise MLAffiliateFetchError(
                f'Resposta não é JSON na página {page}: {exc}'
            ) from exc

        items = _extract_items(payload)
        if not items:
            break

        novos = 0
        for raw in items:
            record = _to_record(raw)
            if record is None or record.sale_id in seen:
                continue
            seen.add(record.sale_id)
            records.append(record)
            novos += 1

        log.info(
            'ml_affiliate_sales page=%d itens=%d novos=%d acumulado=%d',
            page, len(items), novos, len(records),
        )

        if len(items) < items_per_page:
            break
    else:
        log.warning(
            'ml_affiliate_sales atingiu max_pages=%d — pode haver venda não coletada.',
            max_pages,
        )

    return records


def parse_sales_payload(payload) -> list[SaleRecord]:
    """Converte um payload já obtido (arquivo salvo, fixture de teste) em vendas.

    Mesmo caminho de normalização usado por `fetch_sales`, exposto separado para
    permitir backfill a partir de JSON salvo sem bater no ML.
    """
    records: list[SaleRecord] = []
    seen: set[str] = set()
    for raw in _extract_items(payload):
        record = _to_record(raw)
        if record is None or record.sale_id in seen:
            continue
        seen.add(record.sale_id)
        records.append(record)
    return records


def _extract_items(payload) -> list[dict]:
    """Acha a lista de vendas sem assumir o nome exato do envelope.

    O painel já mudou de envelope antes (o relatório agregado usa `item_list`);
    procurar pela forma do item em vez da chave evita quebrar a rotina inteira
    por um rename do lado deles.
    """
    if isinstance(payload, list):
        return [x for x in payload if _is_sale(x)]
    if not isinstance(payload, dict):
        return []
    if _is_sale(payload):
        return [payload]
    for value in payload.values():
        found = _extract_items(value)
        if found:
            return found
    return []


def _is_sale(item) -> bool:
    return (
        isinstance(item, dict)
        and 'saleValue' in item
        and 'commissionValue' in item
    )


def _to_record(raw: dict) -> SaleRecord | None:
    sale_id = str(raw.get('id') or '').strip()
    sale_date = _parse_date(raw.get('date'))
    if not sale_id or sale_date is None:
        log.warning('ml_affiliate_sales item sem id/date utilizável: %.120s', raw)
        return None
    return SaleRecord(
        sale_id=sale_id,
        sale_date=sale_date,
        product_name=str(raw.get('productName') or '')[:255],
        product_link=str(raw.get('link') or ''),
        category_name=str(raw.get('categoryName') or '')[:120],
        store_name=str(raw.get('storeName') or '')[:120],
        sale_value=_to_float(raw.get('saleValue')),
        sale_units=int(_to_float(raw.get('saleUnits')) or 1),
        commission_value=_to_float(raw.get('commissionValue')),
        commission_percentage=_to_float(raw.get('commissionPercentage')),
        sale_type=str(raw.get('saleType') or '')[:32],
        status=str(raw.get('status') or '')[:32],
        status_detail=str(raw.get('statusDetail') or '')[:255],
    )


def _parse_date(value) -> date | None:
    """Aceita `dd/mm/aaaa` (formato observado) e ISO, nesta ordem."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def _to_float(value) -> float:
    if value in (None, ''):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_mlb(link: str) -> str:
    """Extrai `MLB<digitos>` de link de produto. Link de catálogo (`/p/MLB…`)
    devolve string vazia de propósito — é outro namespace e casar por ele
    produziria join errado."""
    if not link or '/p/MLB' in link:
        return ''
    marker = 'MLB-'
    idx = link.find(marker)
    if idx == -1:
        return ''
    rest = link[idx + len(marker):]
    digits = ''
    for char in rest:
        if char.isdigit():
            digits += char
        else:
            break
    return f'MLB{digits}' if digits else ''


def _iso(day: date, *, end_of_day: bool = False) -> str:
    moment = datetime.combine(day, time(23, 59, 59) if end_of_day else time.min)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.000') + BRT_OFFSET
