import logging
import os
import random
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=True)
except ImportError:
    pass

from apps.analytics.services.alertas import enviar_alerta_operador
from apps.marketplaces.services.mercadolivre_affiliate_adapter import (
    ExistingAffiliateLinkEngineAdapter,
)
from apps.marketplaces.services.mercadolivre_product_normalizer import (
    MercadoLivreProductNormalizer,
)
from apps.offers.services.normalizer import (
    OfferNormalizationError,
    get_mercadolivre_path_item_id,
)
from scrapers.base import HTTP_EXCEPTIONS, BaseScraper, build_impersonated_session

log = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)
MAX_PAGES = 5
MIN_DISCOUNT = 5
DELAY_MIN = 2.0
DELAY_MAX = 4.5
_ALLOWED_FETCH_HOSTS = frozenset({
    'meli.la',
    'mercadolivre.com.br',
    'www.mercadolivre.com.br',
    'lista.mercadolivre.com.br',
    'produto.mercadolivre.com.br',
})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECT_HOPS = 3
# Domínio dos cookies da sessão autenticada usados na coleta. Fica restrito ao
# mercadolivre.com.br: meli.la e outros hosts não recebem a sessão.
_SESSION_COOKIE_DOMAIN = '.mercadolivre.com.br'
# Desde 2026-10-16 o ML responde HTTP 200 sem cards para tráfego anônimo:
# /ofertas traz um desafio antibot com prova de trabalho e as categorias pedem
# login. Sem estes marcadores o runner registrava "verificar seletor".
_ACCESS_WALL_MARKERS = (
    ('desafio_antibot', '/security/bot_challenge'),
    ('desafio_antibot', 'document.cookie=`_bmc='),
    ('login_obrigatorio', 'para continuar, acesse sua conta'),
    ('login_obrigatorio', '/gz/account-verification'),
)


# "Selecionados para você" do hub de afiliados (2026-10-22). Rota interna usada
# pelo próprio portal: POST com filtros em lista [{id, value}]. Responde com a
# sessão logada da conta de afiliado (ML_COOKIE) e não passa pelo desafio antibot
# das páginas /ofertas.
AFFILIATE_HUB_SEARCH_URL = 'https://www.mercadolivre.com.br/affiliate-program/api/hub/search'
AFFILIATE_HUB_REFERER = 'https://www.mercadolivre.com.br/afiliados/hub'
_HUB_IMAGE_TEMPLATE = 'https://http2.mlstatic.com/D_NQ_NP_{picture_id}-O.webp'
_HUB_PICTURE_ID_RE = re.compile(r'^[0-9]+-ML[A-Z][0-9]+_[0-9]+$')
_HUB_ITEM_ID_RE = re.compile(r'^MLB([0-9]+)$')


def _parse_cookie_header(value: str) -> list[tuple[str, str]]:
    pairs = []
    for part in str(value or '').split(';'):
        name, sep, cookie_value = part.strip().partition('=')
        name = name.strip()
        if not sep or not name or _contains_url_control(name + cookie_value):
            continue
        pairs.append((name, cookie_value.strip()))
    return pairs


def _normalize_for_match(value: str) -> str:
    """Forma canônica para casar título de `og:title` com título de card."""
    folded = unicodedata.normalize('NFKD', value or '')
    folded = ''.join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', folded).strip().lower()


def _is_allowed_fetch_url(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if _contains_url_control(value):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except (TypeError, ValueError):
        return False
    decoded_path = _decode_fetch_path(parts.path)
    return (
        parts.scheme == 'https'
        and parts.hostname is not None
        and parts.hostname.lower() in _ALLOWED_FETCH_HOSTS
        and port is None
        and parts.username is None
        and parts.password is None
        and bool(parts.path)
        and decoded_path is not None
        and decoded_path == parts.path
        and '\\' not in decoded_path
        and not any(segment in {'.', '..'} for segment in decoded_path.split('/'))
        and not parts.fragment
    )


def _contains_url_control(value: str) -> bool:
    decoded = value
    for _ in range(5):
        if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
            return True
        unquoted = urllib.parse.unquote(decoded)
        if unquoted == decoded:
            return False
        decoded = unquoted
    return any(ord(char) < 32 or ord(char) == 127 for char in decoded)


def _decode_fetch_path(path: str) -> str | None:
    decoded = path
    for _ in range(5):
        unquoted = urllib.parse.unquote(decoded)
        if unquoted == decoded:
            return decoded
        decoded = unquoted
    return None


def _hub_money(value) -> float:
    """Valor de `current_price`/`previous_price` de um polycard do hub."""
    raw = value.get('value') if isinstance(value, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    if isinstance(value, dict) and value.get('currency') not in (None, 'BRL'):
        return 0.0
    return float(raw) if raw > 0 else 0.0


def _hub_int(text) -> int:
    match = re.search(r'(\d+)', str(text or ''))
    return int(match.group(1)) if match else 0


def _hub_rating(component) -> float:
    values = ((component or {}).get('review_compacted') or {}).get('values') or []
    for entry in values:
        if isinstance(entry, dict) and entry.get('key') == 'label':
            text = str(((entry.get('label') or {}).get('text')) or '').replace(',', '.')
            try:
                rating = float(text)
            except ValueError:
                return 0.0
            return rating if 0 < rating <= 5 else 0.0
    return 0.0


def _hub_image_url(card: dict) -> str:
    pictures = ((card.get('pictures') or {}).get('pictures')) or []
    picture_id = pictures[0].get('id') if pictures and isinstance(pictures[0], dict) else ''
    if isinstance(picture_id, str) and _HUB_PICTURE_ID_RE.fullmatch(picture_id):
        return _HUB_IMAGE_TEMPLATE.format(picture_id=picture_id)
    return ''


@dataclass
class MercadoLivreOffer:
    id: str
    nome: str
    preco: float
    preco_original: float
    desconto_pct: int
    link_direto: str
    link_afiliado: str
    imagem: str
    vendedor: str
    condicao: str
    frete_gratis: bool
    data: str
    review_rating: float = 0.0
    review_count: int = 0

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'nome': self.nome,
            'preco': self.preco,
            'preco_original': self.preco_original,
            'desconto_pct': self.desconto_pct,
            'link_direto': self.link_direto,
            'link_afiliado': self.link_afiliado,
            'imagem': self.imagem,
            'vendedor': self.vendedor,
            'condicao': self.condicao,
            'frete_gratis': self.frete_gratis,
            'data': self.data,
            'review_rating': self.review_rating,
            'review_count': self.review_count,
        }


class MercadoLivreScraper(BaseScraper):
    def __init__(
        self,
        affiliate_id: str = '',
        affiliate_tag: str = '',
        ml_cookie: str = '',
        ml_csrf: str = '',
    ):
        self.affiliate_id = affiliate_id
        self.affiliate_tag = affiliate_tag
        self.ml_cookie = ml_cookie
        self.ml_csrf = ml_csrf
        self.today = datetime.now(timezone(BRT_OFFSET)).date()
        self.pages_scraped = 0
        self.blocked = False
        self.error_message = ''
        self.affiliate_hub_error = ''
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        # curl_cffi impersona o TLS fingerprint do Chrome para reduzir bloqueio
        # anti-bot (mesma abordagem do scrapers/amazon.py); fallback gracioso
        # para requests puro se curl_cffi não estiver instalado.
        self.session = build_impersonated_session('chrome124')
        self.session_cookie_count = self._load_session_cookies(self.ml_cookie)
        self._affiliate_adapter = ExistingAffiliateLinkEngineAdapter(
            affiliate_tag=self.affiliate_tag,
            ml_cookie=self.ml_cookie,
            ml_csrf=self.ml_csrf,
            session_factory=lambda: build_impersonated_session('chrome124'),
            alert_callback=self._exibir_alerta_cookie,
        )

    def _load_session_cookies(self, cookie_header: str) -> int:
        """Carrega ML_COOKIE no jar da sessão de coleta, só para mercadolivre.com.br.

        O jar (e não um header fixo) mantém o escopo por domínio e aceita os
        Set-Cookie de renovação que o ML devolver durante o ciclo.
        """
        cookies = getattr(self.session, 'cookies', None)
        if cookies is None:
            return 0
        loaded = 0
        for name, value in _parse_cookie_header(cookie_header):
            try:
                cookies.set(name, value, domain=_SESSION_COOKIE_DOMAIN, path='/')
            except Exception as exc:  # noqa: BLE001 - nunca derrubar a coleta pelo jar
                log.warning('ml_session_cookie_ignorado erro=%s', type(exc).__name__)
                continue
            loaded += 1
        return loaded

    @staticmethod
    def detect_access_wall(html: str) -> str:
        content = (html or '').lower()
        # Página com cards é página útil, mesmo se o cabeçalho citar verificação.
        if 'poly-card' in content or 'ui-search-result' in content:
            return ''
        for reason, marker in _ACCESS_WALL_MARKERS:
            if marker.lower() in content:
                return reason
        return ''

    def _check_blocked(self, html: str, where: str) -> bool:
        if self.is_blocked(html):
            self.blocked = True
            self.error_message = f'CAPTCHA detectado em {where}'
            log.error('CAPTCHA detectado em %s.', where)
            return True
        reason = self.detect_access_wall(html)
        if not reason:
            return False
        self.blocked = True
        session_state = 'com_sessao' if self.session_cookie_count else 'sem_sessao'
        self.error_message = (
            f'Mercado Livre exigiu login/desafio antibot ({reason}, {session_state}) '
            f'em {where}; renove ML_COOKIE no .env com a sessão de um navegador logado.'
        )
        log.error(
            'ml_access_wall motivo=%s sessao=%s cookies=%d em=%s',
            reason, session_state, self.session_cookie_count, where,
        )
        self._exibir_alerta_cookie(motivo=f'coleta_{reason}')
        return True

    def _fetch_ml_response(self, url: str):
        current_url = url
        for hop in range(_MAX_REDIRECT_HOPS + 1):
            if not _is_allowed_fetch_url(current_url):
                raise ValueError('URL de coleta do Mercado Livre não permitida.')
            response = self.fetch_with_retry(
                self.session,
                current_url,
                headers=self.headers,
                timeout=20,
                allow_redirects=False,
            )
            status = getattr(response, 'status_code', None)
            if isinstance(status, bool) or not isinstance(status, int):
                raise ValueError('Resposta HTTP inválida na coleta do Mercado Livre.')
            if status not in _REDIRECT_STATUS_CODES:
                return response
            if hop >= _MAX_REDIRECT_HOPS:
                raise ValueError('Cadeia de redirecionamento do Mercado Livre excedeu o limite.')
            headers = getattr(response, 'headers', {}) or {}
            location = headers.get('Location') or headers.get('location')
            if not isinstance(location, str) or not location.strip():
                raise ValueError('Redirecionamento do Mercado Livre sem destino válido.')
            if _contains_url_control(location):
                raise ValueError('Redirecionamento do Mercado Livre contém controle inválido.')
            current_url = urllib.parse.urljoin(current_url, location.strip())
        raise ValueError('Cadeia de redirecionamento do Mercado Livre inválida.')

    def get_html(self, url: str) -> str:
        try:
            resp = self._fetch_ml_response(url)
            if resp.status_code == 403:
                self.blocked = True
                self.error_message = 'Acesso negado 403 na coleta do Mercado Livre.'
                log.error('Acesso negado 403 na coleta do Mercado Livre.')
                return ''
            resp.raise_for_status()
            return resp.text
        except ValueError as exc:
            self.error_message = 'URL ou redirecionamento inválido na coleta do Mercado Livre.'
            log.error('URL/redirecionamento rejeitado no Mercado Livre: %s', type(exc).__name__)
            return ''
        except HTTP_EXCEPTIONS as exc:
            self.error_message = 'Falha HTTP na coleta do Mercado Livre.'
            log.error('Falha HTTP na coleta do Mercado Livre: %s', type(exc).__name__)
            return ''
        except Exception as exc:  # noqa: BLE001 - fronteira externa fail-closed
            self.error_message = 'Falha inesperada na coleta do Mercado Livre.'
            log.error('Falha inesperada na coleta do Mercado Livre: %s', type(exc).__name__)
            return ''

    def scrape_daily_deals(self, max_pages: int = MAX_PAGES) -> list[dict]:
        all_offers: list[dict] = []
        seen_ids: set[str] = set()

        for page in range(1, max_pages + 1):
            url = f'https://www.mercadolivre.com.br/ofertas?page={page}'
            log.info('Buscando página %d/%d: %s', page, max_pages, url)

            html = self.get_html(url)
            if not html:
                break

            if self._check_blocked(html, f'página {page}'):
                break

            self.pages_scraped = page
            page_offers = self._extract_poly_cards(html, page)
            for offer in page_offers:
                data = offer.to_dict()
                if data['id'] not in seen_ids:
                    seen_ids.add(data['id'])
                    all_offers.append(data)

            if not page_offers:
                break

            if page < max_pages:
                time.sleep(round(random.uniform(DELAY_MIN, DELAY_MAX), 2))

        return all_offers

    def scrape_categories(self, targets: list[tuple]) -> list[dict]:
        """Sprint 5: itera URLs declaradas em scrapers/category_targets.py.

        targets: lista de (category_code, label, url) ou (category_code, label, url, trust_hint).
        Quando trust_hint=False, omite category_hint do payload — útil para
        URLs ML que viraram categoria-pai genérica (MLB1430 vestuário inteiro),
        deixando o classifier de keywords decidir a categoria pelo título.
        """
        all_offers: list[dict] = []
        seen_ids: set[str] = set()
        total = len(targets)

        for idx, target in enumerate(targets):
            category_code, label, url, *rest = target
            trust_hint = rest[0] if rest else True

            if self.blocked:
                break

            log.info('Buscando ofertas ML [%s] (%d/%d): %s', label, idx + 1, total, url)
            html = self.get_html(url)
            if not html:
                log.warning('[%s] sem HTML — categoria ignorada', label)
                continue

            if self._check_blocked(html, f'{url} (categoria {label})'):
                break

            self.pages_scraped += 1
            page_offers = self._extract_poly_cards(html, idx + 1)
            captured = 0
            for offer in page_offers:
                data = offer.to_dict()
                if data['id'] in seen_ids:
                    continue
                seen_ids.add(data['id'])
                data['source_label'] = label
                if category_code and trust_hint:
                    data['category_hint'] = category_code
                all_offers.append(data)
                captured += 1

            log.info(
                '[%s] %d cards | %d novas | total acumulado: %d',
                label, len(page_offers), captured, len(all_offers),
            )

            if idx < total - 1:
                time.sleep(round(random.uniform(DELAY_MIN, DELAY_MAX), 2))

        return all_offers

    def scrape_affiliate_hub(
        self,
        targets: list[tuple],
        include_extra_commission: bool = True,
    ) -> list[dict]:
        """Coleta o "Selecionados para você" do hub de afiliados (2026-10-22).

        targets: lista de (category_code, label, category_id, trust_hint,
        min_discount, max_price). Para cada categoria busca a primeira página por
        relevância e, opcionalmente, a primeira página só com comissão extra.

        As regras de desconto mínimo e teto de preço da categoria são aplicadas
        antes do motor afiliado, para não gerar link de item que seria descartado
        logo depois por `_apply_category_filters`.
        """
        all_offers: list[dict] = []
        seen_ids: set[str] = set()
        stopped = False

        for category_code, label, category_id, trust_hint, min_discount, max_price in targets:
            filter_sets = [[{'id': 'category', 'value': category_id}]]
            if include_extra_commission:
                filter_sets.append([
                    {'id': 'category', 'value': category_id},
                    {'id': 'extra_commission', 'value': True},
                ])
            for filters in filter_sets:
                if stopped:
                    break
                cards, stopped = self._fetch_affiliate_hub_cards(filters)
                captured = 0
                for card in cards:
                    parsed = self._parse_affiliate_hub_card(card, min_discount, max_price, seen_ids)
                    if parsed is None:
                        continue
                    offer, signals = parsed
                    seen_ids.add(offer.id)
                    data = offer.to_dict()
                    data['source_label'] = f'hub:{label}'
                    data['marketplace_code'] = 'mercadolivre'
                    data['collection_source'] = 'affiliate_hub'
                    data['search_provenance'] = {
                        'source_kind': 'affiliate_hub',
                        'category_code': category_code,
                        'marketplace': 'mercadolivre',
                    }
                    data['affiliate_hub'] = signals
                    if category_code and trust_hint:
                        data['category_hint'] = category_code
                    all_offers.append(data)
                    captured += 1
                extra = len(filters) > 1
                log.info(
                    'ml_affiliate_hub [%s] extra_commission=%s cards=%d aceitos=%d total=%d',
                    label, extra, len(cards), captured, len(all_offers),
                )
                time.sleep(round(random.uniform(DELAY_MIN, DELAY_MAX), 2))
            if stopped:
                break

        return all_offers

    def _affiliate_hub_headers(self) -> dict:
        headers = {
            key: value for key, value in self.headers.items()
            if key not in {'Upgrade-Insecure-Requests', 'Sec-Fetch-User'}
        }
        headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': 'https://www.mercadolivre.com.br',
            'Referer': AFFILIATE_HUB_REFERER,
            'x-custom-origin': 'https://www.mercadolivre.com.br',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        })
        return headers

    def _fetch_affiliate_hub_cards(self, filters: list[dict]) -> tuple[list[dict], bool]:
        """Retorna (cards, parar). Sessão negada interrompe o restante do hub."""
        try:
            response = self.session.post(
                AFFILIATE_HUB_SEARCH_URL,
                params={'is_affiliate': 'true', 'device': 'desktop'},
                json={'search': '', 'filters': filters, 'sort': 'relevance', 'offset': 0},
                headers=self._affiliate_hub_headers(),
                timeout=20,
                allow_redirects=False,
            )
        except HTTP_EXCEPTIONS as exc:
            self.affiliate_hub_error = 'Falha HTTP no hub de afiliados do Mercado Livre.'
            log.warning('ml_affiliate_hub_falha_http erro=%s', type(exc).__name__)
            return [], False

        status = getattr(response, 'status_code', None)
        if status in (401, 403) or (isinstance(status, int) and 300 <= status < 400):
            self.affiliate_hub_error = (
                f'Hub de afiliados recusou a sessão (HTTP {status}); renove ML_COOKIE no .env.'
            )
            log.error('ml_affiliate_hub_sessao_recusada status=%s', status)
            self._exibir_alerta_cookie(motivo=f'hub_afiliados_http_{status}')
            return [], True
        if status != 200:
            self.affiliate_hub_error = f'Hub de afiliados respondeu HTTP {status}.'
            log.warning('ml_affiliate_hub_status status=%s', status)
            return [], status == 429

        try:
            body = response.json()
        except ValueError:
            self.affiliate_hub_error = 'Hub de afiliados retornou resposta não JSON.'
            log.warning('ml_affiliate_hub_resposta_invalida')
            return [], True
        model = body.get('polycard_client_model') if isinstance(body, dict) else None
        cards = model.get('polycards') if isinstance(model, dict) else None
        if not isinstance(cards, list):
            self.affiliate_hub_error = 'Hub de afiliados retornou formato inesperado.'
            log.warning('ml_affiliate_hub_schema_inesperado')
            return [], True
        self.pages_scraped += 1
        return [card for card in cards if isinstance(card, dict)], False

    def _parse_affiliate_hub_card(
        self,
        card: dict,
        min_discount: float,
        max_price: float | None,
        seen_ids: set[str],
    ) -> Optional[tuple[MercadoLivreOffer, dict]]:
        try:
            metadata = card.get('metadata') or {}
            card_type = str(metadata.get('type') or '')
            permalink = self._affiliate_hub_permalink(metadata, card_type)
            if not permalink:
                return None
            item_id = get_mercadolivre_path_item_id(urllib.parse.urlsplit(permalink).path)
            if not item_id or item_id in seen_ids:
                return None
            try:
                permalink = MercadoLivreProductNormalizer._canonical_product_url(item_id, permalink)
            except OfferNormalizationError:
                return None

            components = {
                component.get('type'): component
                for component in card.get('components') or []
                if isinstance(component, dict)
            }
            title = str(((components.get('title') or {}).get('title') or {}).get('text') or '').strip()
            price_block = (components.get('price') or {}).get('price') or {}
            price = _hub_money(price_block.get('current_price'))
            if not title or price <= 0:
                return None
            original_price = _hub_money(price_block.get('previous_price')) or price
            discount_pct = _hub_int(((price_block.get('discount_label') or {}).get('text')))
            if discount_pct == 0 and original_price > price:
                discount_pct = round((original_price - price) / original_price * 100)
            if discount_pct < max(MIN_DISCOUNT, float(min_discount or 0)):
                return None
            if max_price is not None and price > float(max_price):
                return None

            signals = {
                'card_type': card_type,
                'extra_commission': str(metadata.get('extra_commission') or '').lower() == 'true',
                'commission_pct': _hub_int(
                    (((components.get('chip') or {}).get('chip') or {}).get('label') or {}).get('text'),
                ),
                'highlight': re.sub(
                    r'\{[^}]*\}\s*',
                    '',
                    str(((components.get('highlight') or {}).get('highlight') or {}).get('text') or ''),
                ).strip()[:60],
            }
            offer = MercadoLivreOffer(
                id=item_id,
                nome=title,
                preco=price,
                preco_original=original_price,
                desconto_pct=discount_pct,
                link_direto=permalink,
                link_afiliado=self._gerar_link_afiliado_oficial(permalink),
                imagem=_hub_image_url(card),
                vendedor='',
                condicao='Novo',
                frete_gratis=False,
                data=datetime.now(timezone(BRT_OFFSET)).strftime('%Y-%m-%d'),
                review_rating=_hub_rating(components.get('review_compacted')),
                review_count=0,
            )
            return offer, signals
        except Exception as exc:  # noqa: BLE001 - card externo isolado
            log.debug('Erro ao parsear card do hub: %s', type(exc).__name__)
            return None

    @staticmethod
    def _affiliate_hub_permalink(metadata: dict, card_type: str) -> str:
        raw_id = str(metadata.get('id') or '').strip().upper()
        if card_type == 'user_product':
            # /up/MLBU... não tem identidade de anúncio no caminho; a página do
            # anúncio (metadata.id) leva ao mesmo produto e tem identidade estável.
            match = _HUB_ITEM_ID_RE.fullmatch(raw_id)
            return f'https://produto.mercadolivre.com.br/MLB-{match.group(1)}' if match else ''
        url = metadata.get('url')
        if not isinstance(url, str) or not url or _contains_url_control(url):
            return ''
        url = url.split('#', 1)[0].split('?', 1)[0]
        return url if url.startswith('https://') else f'https://{url}'

    def scrape_search_queries(self, queries) -> list[dict]:
        """Busca direcionada por texto livre está DESATIVADA no Mercado Livre.

        Achado B2 (diagnóstico 2026-08-18). O commit 84e5071 (2026-08-12) passou a
        montar `https://lista.mercadolivre.com.br/{slug}` — domínio bloqueado pelo
        Akamai, o mesmo de que `category_targets.py` já havia migrado. Verificação
        ao vivo em 2026-08-18, com a sessão impersonada real do scraper:

        - `lista.mercadolivre.com.br/{slug}` sem cookie → 200 com 10KB de HTML e
          zero cards, ou redirect para `/gz/account-verification`.
        - `www.mercadolivre.com.br/jm/search?as_word=` → redireciona para
          `/gz/account-verification`.
        - `www.mercadolivre.com.br/search?q=` → 404.
        - `www.mercadolivre.com.br/ofertas?q=` → 200 com 45 cards, MAS o parâmetro
          `q` é ignorado: os 45 títulos são idênticos aos de `/ofertas` sem `q`,
          para qualquer termo. Falso positivo — pareceria funcionar e devolveria
          ofertas genéricas com proveniência de busca direcionada, o que é pior do
          que não buscar.
        - `lista.mercadolivre.com.br/{slug}` COM `ML_COOKIE` → 200, 964KB,
          `<title>Cafeteira | Mercado Livre</title>` (a busca certa!), mas **zero**
          cards no HTML servido: a página virou React streaming SSR (`_n.ctx`,
          `$RC(...)`), sem `__PRELOADED_STATE__`, sem `ld+json` e sem `.poly-card`.
          Extrair dali exige navegador headless ou engenharia reversa do payload
          de streaming — outro scraper, não um ajuste de URL.

        Contenção adotada: o ML não faz busca direcionada por texto livre. Amazon e
        Shopee seguem normalmente (não dependem desse domínio), e o ML continua
        coletando por `scrape_categories` (URLs de categoria fixa em
        `www.mercadolivre.com.br/ofertas?category=MLB...`, que funcionam) e por
        `scrape_daily_deals`.

        Retorna lista vazia de propósito: `ScraperAdapter.collect()` então cai no
        fallback de categoria/daily deals, que é o caminho que de fato funciona.
        """
        if queries:
            log.warning(
                'ml_directed_search_skipped queries=%d motivo=busca_por_texto_sem_url_scrapavel '
                '(ver docstring de scrape_search_queries e docs/DIAGNOSTICO_ENVIOS_COLETA_2026-08-18.md)',
                len(queries),
            )
        return []

    # `_scrape_search_urls` foi removido junto com a busca direcionada por texto
    # (achado B2, 2026-08-18): era usado só por `scrape_search_queries` e todas as
    # URLs que ele recebia eram do domínio bloqueado. `scrape_categories` tem seu
    # próprio loop, com paginação e `category_hint`.

    def scrape_social_card(self, url: str) -> Optional[dict]:
        """Resolve um link encurtado de vitrine de afiliado (`meli.la/...`) no anúncio.

        É o caminho de coleta do radar de concorrente (2026-08-21). Os grupos de
        oferta divulgam `meli.la/<hash>`, que redireciona para
        `www.mercadolivre.com.br/social/<vitrine>` — a página de afiliado de quem
        publicou, com o anúncio-alvo em destaque e o resto do catálogo dele abaixo.

        Verificado ao vivo em 2026-08-21, com a sessão impersonada do scraper:
        essa página responde **200 com HTML completo** (270-365KB) e usa os mesmos
        `.poly-card` das páginas de categoria, então `_parse_item` funciona sem
        adaptação — o que também garante que o `external_id` extraído aqui é o
        mesmo que o da coleta por categoria (identidade consistente, requisito
        para o dedup por `produto_canonico_id`). As páginas do anúncio em si
        continuam bloqueadas: `produto.mercadolivre.com.br/MLB-...` devolve
        micro-landing de 9KB e `/p/MLB...` redireciona para
        `/gz/account-verification`. Por isso o preço sai do card da vitrine, não
        da página do produto.

        O alvo é escolhido pelo `og:title`, que a vitrine preenche com o anúncio
        do link, e **só** por ele: sem casamento, devolve `None`. O ID do anúncio
        **não** pode sair do `og:image`: o nome do arquivo de imagem carrega o ID
        do *asset* (`D_NQ_NP_..-MLB78955357177_..`), que é diferente do ID do item
        (`MLB-3656481579` no href do mesmo card) e às vezes nem é do site
        brasileiro (`MLA...`).
        """
        html = self.get_html(url)
        if not html:
            return None
        if self._check_blocked(html, f'vitrine social {url}'):
            return None

        soup = BeautifulSoup(html, 'html.parser')
        card = self._find_social_target_card(soup)
        if card is None:
            log.info('social_card_sem_alvo url=%s', url)
            return None

        offer = self._parse_item(card)
        if offer is None:
            return None
        return offer.to_dict()

    def _find_social_target_card(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        cards = soup.select('.poly-card')
        if not cards:
            return None

        og_title = soup.find('meta', property='og:title')
        expected = _normalize_for_match(og_title.get('content', '') if og_title else '')
        if not expected:
            log.info('social_card_sem_og_title cards=%d', len(cards))
            return None

        titles = [
            (card, _normalize_for_match(title_el.get_text(strip=True)))
            for card in cards
            if (title_el := card.select_one('.poly-component__title'))
        ]
        for card, title in titles:
            if title == expected:
                return card
        for card, title in titles:
            if expected in title or title in expected:
                return card

        # Sem casamento, o link não tem alvo identificável: ou aponta para a raiz
        # da vitrine (`og:title` vira "minhas recomendações") ou o produto
        # anunciado saiu do ar. O card em destaque é uma oferta real, mas **não é
        # a oferta anunciada** — chutar nele trocava o produto em silêncio
        # (2026-08-21: mensagem de "micro-ondas consul cms23ab" resolveu num
        # "Micro-ondas MTO30", e "Insider Light T-Shirt" na "Daily T-shirt").
        # Isso derruba a premissa do radar, que é publicar a oferta que os grupos
        # estão empurrando. Melhor não resolver.
        log.info('social_card_alvo_nao_identificado og_title=%s cards=%d', expected[:60], len(cards))
        return None

    def _extract_poly_cards(self, html: str, page: int) -> list[MercadoLivreOffer]:
        soup = BeautifulSoup(html, 'html.parser')
        items = (
            soup.select('.poly-card')
            or soup.select('.ui-search-result')
            or soup.select('[class*=deals-item]')
        )
        log.info('Página %d: %d cards encontrados', page, len(items))
        offers = []
        for card in items:
            offer = self._parse_item(card)
            if offer:
                offers.append(offer)
        return offers

    def _parse_item(self, card: BeautifulSoup) -> Optional[MercadoLivreOffer]:
        try:
            title_el = (
                card.select_one('.poly-component__title')
                or card.select_one('.ui-search-item__title')
                or card.select_one('a[class*=title]')
            )
            if not title_el:
                return None

            title = title_el.get_text(strip=True)
            title = re.sub(
                r'^\s*an[uú]ncio\s+patrocinado\s*[\-–—:]\s*',
                '',
                title,
                flags=re.IGNORECASE,
            ).strip()
            permalink = title_el.get('href', '')
            if not isinstance(permalink, str) or not permalink:
                return None
            if _contains_url_control(permalink):
                return None
            is_tracking_wrapper = 'click1.mercadolivre' in permalink or 'mclics' in permalink
            if is_tracking_wrapper:
                parsed = urllib.parse.urlparse(permalink)
                qs = urllib.parse.parse_qs(parsed.query)
                target = qs.get('url', [None])[0]
                if not isinstance(target, str) or not target or _contains_url_control(target):
                    return None
                permalink = target
            if not permalink or not title:
                return None

            # A identidade vem do caminho, nunca de pdp_filters/tracking.
            # O normalizador valida a URL e remove query/fragmento depois.
            item_id = get_mercadolivre_path_item_id(
                urllib.parse.urlsplit(permalink).path,
            )
            if not item_id:
                return None

            try:
                permalink = MercadoLivreProductNormalizer._canonical_product_url(
                    item_id,
                    permalink,
                )
            except OfferNormalizationError:
                return None

            price_fraction = (
                card.select_one('.poly-price__current .andes-money-amount__fraction')
                or card.select_one('.andes-money-amount__fraction')
            )
            price = 0.0
            if price_fraction:
                try:
                    price = float(price_fraction.get_text(strip=True).replace('.', '').replace(',', '.'))
                except ValueError:
                    pass
            if price <= 0:
                return None

            original_price = price
            old_price_el = (
                card.select_one('s.andes-money-amount--previous .andes-money-amount__fraction')
                or card.select_one('.poly-price__original .andes-money-amount__fraction')
                or card.select_one('[class*=original] .andes-money-amount__fraction')
            )
            if old_price_el:
                try:
                    original_price = float(old_price_el.get_text(strip=True).replace('.', '').replace(',', '.'))
                except ValueError:
                    pass

            discount_pct = 0
            discount_el = card.select_one('.poly-price__discount') or card.select_one('[class*=discount]')
            if discount_el:
                discount_match = re.search(r'(\d+)\s*%', discount_el.get_text())
                if discount_match:
                    discount_pct = int(discount_match.group(1))
            if discount_pct == 0 and original_price > price:
                discount_pct = round((original_price - price) / original_price * 100)
            if discount_pct < MIN_DISCOUNT:
                return None

            img_el = (
                card.select_one('.poly-component__picture')
                or card.select_one('img[class*=item]')
                or card.select_one('img')
            )
            image = ''
            if img_el:
                image = img_el.get('data-src') or img_el.get('src', '')
            image = (
                image
                .replace('http://', 'https://')
                .replace('-W.webp', '-O.webp')
                .replace('-E.webp', '-O.webp')
                .replace('-V.webp', '-O.webp')
            )

            shipping_el = card.select_one('.poly-component__shipping') or card.select_one('[class*=shipping]')
            has_free_shipping = bool(
                shipping_el
                and any(kw in shipping_el.get_text().lower() for kw in ['grátis', 'gratis', 'free'])
            )

            seller_el = card.select_one('.poly-component__seller') or card.select_one('[class*=seller]')
            seller = 'Top Vendedor ML'
            if seller_el:
                seller = seller_el.get_text(strip=True).replace('Por', '').strip() or seller

            affiliate_url = self._gerar_link_afiliado_oficial(permalink)

            review_rating, review_count = self._extract_reviews(card)

            return MercadoLivreOffer(
                id=item_id,
                nome=title,
                preco=price,
                preco_original=original_price,
                desconto_pct=discount_pct,
                link_direto=permalink,
                link_afiliado=affiliate_url,
                imagem=image,
                vendedor=seller,
                condicao='Novo',
                frete_gratis=has_free_shipping,
                data=datetime.now(timezone(BRT_OFFSET)).strftime('%Y-%m-%d'),
                review_rating=review_rating,
                review_count=review_count,
            )
        except Exception as exc:
            log.debug('Erro ao parsear card: %s', type(exc).__name__)
            return None

    def _extract_reviews(self, card: BeautifulSoup) -> tuple[float, int]:
        # ML expõe nota e total na listagem em .poly-reviews__rating e .poly-reviews__total
        rating = 0.0
        rating_el = (
            card.select_one('.poly-reviews__rating')
            or card.select_one('.ui-search-reviews__rating-number')
        )
        if rating_el:
            m = re.search(r'(\d+[\.,]\d+)', rating_el.get_text())
            if m:
                try:
                    rating = float(m.group(1).replace(',', '.'))
                    if rating < 0 or rating > 5:
                        rating = 0.0
                except ValueError:
                    rating = 0.0

        count = 0
        count_el = (
            card.select_one('.poly-reviews__total')
            or card.select_one('.ui-search-reviews__amount')
        )
        if count_el:
            text = re.sub(r'[^\d]', '', count_el.get_text())
            if text:
                try:
                    count = int(text)
                except ValueError:
                    count = 0

        return rating, count

    def _exibir_alerta_cookie(self, motivo: str = 'expirado_ou_ausente') -> None:
        # Dispara no máximo 1x por ciclo de scraping (uma instância de
        # MercadoLivreScraper = um ciclo) — evita floodar o operador com um
        # alerta por oferta quando o cookie está inválido para o ciclo inteiro.
        if getattr(self, '_alerta_exibido', False):
            return
        self._alerta_exibido = True
        mensagem = (
            'Cookie/token do Mercado Livre expirou, foi rejeitado ou está ausente '
            f'(motivo: {motivo}). Renove ML_COOKIE e ML_CSRF_TOKEN no .env.'
        )
        log.error('ATENÇÃO: %s', mensagem)
        enviar_alerta_operador(mensagem, categoria='ml_cookie_expirado')

    def _gerar_link_afiliado_oficial(self, permalink: str) -> str:
        return self._affiliate_adapter.generate(permalink)


def build_from_env() -> MercadoLivreScraper:
    return MercadoLivreScraper(
        affiliate_id=os.environ.get('ML_AFFILIATE_ID', ''),
        affiliate_tag=os.environ.get('ML_AFFILIATE_TAG', ''),
        ml_cookie=os.environ.get('ML_COOKIE', ''),
        ml_csrf=os.environ.get('ML_CSRF_TOKEN', ''),
    )
