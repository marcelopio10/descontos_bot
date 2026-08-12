import logging
import os
import random
import re
import time
import hashlib
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

from scrapers.base import build_impersonated_session
from apps.marketplaces.services.search_provenance import sanitize_search_provenance

log = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)
MIN_DISCOUNT = 5
DELAY_MIN = 3.0
DELAY_MAX = 6.0

# Backoff exponencial com jitter para `get_html`: tentativa N (N>1) espera
# min(2**(N-1), BACKOFF_CAP_SECONDS) segundos + jitter aleatório uniforme em
# [0, BACKOFF_JITTER_SECONDS) — ex.: tentativas 2/3/4 esperam ~2s/~4s/~8s de
# base. O jitter evita que retries de várias categorias/execuções fiquem
# sincronizados no mesmo instante (efeito manada) e reduz a regularidade de
# timing que sistemas anti-bot usam como sinal. `AmazonScraper(rng=...)`
# aceita um `random.Random` injetável para tornar o teste determinístico.
BACKOFF_CAP_SECONDS = 30.0
BACKOFF_JITTER_SECONDS = 1.0
MAX_ATTEMPTS = 4

ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})')

# Páginas de ofertas da Amazon, identificadas por categoria.
# Cada entrada é uma fonte distinta — todas são raspadas no mesmo ciclo
# (max_pages é ignorado neste scraper; ver scrape_daily_deals).
DEAL_URLS: list[tuple[str, str]] = [
    #('Ofertas do Dia',  'https://www.amazon.com.br/deals'),
    #('Goldbox',         'https://www.amazon.com.br/gp/goldbox'),
    ('Eletrônicos',     'https://www.amazon.com.br/s?i=aps&deal-type=eligible&rh=n%3A1229514011'),
    ('Esporte e Lazer', 'https://www.amazon.com.br/s?i=aps&deal-type=eligible&rh=n%3A14617390011'),
    ('Moda',            'https://www.amazon.com.br/s?k=moda&i=apparel&deal-type=eligible'),
    ('Casa e Cozinha',  'https://www.amazon.com.br/s?k=casa&i=kitchen&deal-type=eligible'),
    ('Beleza',          'https://www.amazon.com.br/s?k=beleza&i=beauty&deal-type=eligible'),
    ('Brinquedos',      'https://www.amazon.com.br/s?k=brinquedos&i=toys&deal-type=eligible'),
    ('Supermercado',    'https://www.amazon.com.br/s?k=mercado&i=grocery&deal-type=eligible'),
    ('Bebidas Alcoólicas', 'https://www.amazon.com.br/s?k=bebidas+alcoolicas&deal-type=eligible'),
    ('Vinhos',          'https://www.amazon.com.br/s?k=vinho&deal-type=eligible'),
    ('Mais Vendidos',   'https://www.amazon.com.br/gp/bestsellers/?ref_=nav_em_cs_bestsellers_0_1_1_2'),
    ('Maiores Altas',   'https://www.amazon.com.br/gp/movers-and-shakers/?ref_=nav_em_ms_0_1_1_4'),
]


@dataclass
class AmazonOffer:
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
    source_label: str = ''
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
            'source_label': self.source_label,
            'review_rating': self.review_rating,
            'review_count': self.review_count,
            'condicao': self.condicao,
            'frete_gratis': self.frete_gratis,
            'data': self.data,
        }


class AmazonScraper:
    """
    Scraper de ofertas Amazon.com.br usando curl-cffi (impersona TLS do Chrome
    para contornar bloqueio anti-bot que rejeita o requests padrão com HTTP 503).
    """

    def __init__(self, associate_tag: str = '', rng: Optional[random.Random] = None):
        self.associate_tag = associate_tag
        self.today = datetime.now(timezone(BRT_OFFSET)).date()
        self.pages_scraped = 0
        self.blocked = False
        self.error_message = ''
        # RNG do jitter de backoff — injetável para tornar testes determinísticos
        # (ex.: `AmazonScraper(rng=random.Random(42))`); por padrão usa o módulo
        # `random` global (não determinístico, ok para uso real).
        self._rng = rng or random
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
        }
        self.session = build_impersonated_session('chrome124')

    @staticmethod
    def is_blocked(html: str) -> bool:
        content = html.lower()
        blocked_markers = [
            'captcha',
            'captcha-page',
            'robot check',
            'verifique que você não é um robô',
        ]
        return any(marker in content for marker in blocked_markers)

    def get_html(self, url: str) -> str:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt > 1:
                backoff = min(2 ** (attempt - 1), BACKOFF_CAP_SECONDS) + self._rng.uniform(0, BACKOFF_JITTER_SECONDS)
                time.sleep(backoff)
            try:
                resp = self.session.get(url, headers=self.headers, timeout=25)
                if resp.status_code == 403:
                    self.blocked = True
                    self.error_message = f'Acesso negado 403 em {url}'
                    log.error('Acesso negado 403. URL: %s', url)
                    return ''
                if resp.status_code >= 500:
                    log.warning('Tentativa %d falhou para %s: HTTP %s', attempt, url, resp.status_code)
                    continue
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                log.warning('Tentativa %d falhou para %s: %s', attempt, url, exc)
        self.error_message = f'Esgotadas as tentativas para {url}'
        log.error('Esgotadas as tentativas para %s', url)
        return ''

    def scrape_categories(self, targets: list[tuple]) -> list[dict]:
        """Versão Sprint 5: itera URLs vindas da configuração por categoria.

        targets: lista de (category_code, label, url) ou
        (category_code, label, url, trust_hint). Quando trust_hint=False,
        omite category_hint do payload e deixa o classifier decidir pelo título.
        """
        normalized_targets: list[tuple[str, str, str, bool]] = []
        for target in targets:
            category_code, label, url, *rest = target
            trust_hint = rest[0] if rest else True
            provenance = rest[1] if len(rest) > 1 else {}
            normalized_targets.append((label, url, category_code, bool(trust_hint), provenance))

        return self._scrape_urls(normalized_targets)

    def scrape_search_queries(self, queries) -> list[dict]:
        items = []
        for query in queries:
            encoded = urllib.parse.quote_plus(query.query_text)
            items.append((
                f'Busca direcionada: {query.query_text}',
                f'https://www.amazon.com.br/s?k={encoded}&deal-type=eligible',
                '',
                False,
                sanitize_search_provenance({
                    'source_kind': query.source_kind,
                    'query_text': query.query_text,
                    'brand': query.brand,
                    'category_code': query.category_code,
                    'price_band': query.price_band,
                    'marketplace': query.marketplace,
                }),
            ))
        return self._scrape_urls(items)

    def scrape_daily_deals(self, max_pages: int = 5) -> list[dict]:
        # max_pages é mantido por compatibilidade de API, mas Amazon raspa todas as
        # categorias em DEAL_URLS por ciclo (cada URL é uma categoria, não paginação).
        del max_pages
        return self._scrape_urls(
            [(label, url, '', True) for label, url in DEAL_URLS],
        )

    def _scrape_urls(self, items: list[tuple[str, str, str, bool]]) -> list[dict]:
        all_offers: list[dict] = []
        seen_ids: set[str] = set()
        total = len(items)

        for idx, item in enumerate(items):
            label, url, category_code, trust_hint, *rest = item
            provenance = rest[0] if rest else {}
            if self.blocked:
                break

            log.info('Buscando ofertas Amazon [%s] (%d/%d): %s', label, idx + 1, total, url)
            html = self.get_html(url)
            if not html:
                log.warning('[%s] sem HTML — categoria ignorada', label)
                continue

            if self.is_blocked(html):
                self.blocked = True
                self.error_message = f'CAPTCHA detectado em {url}'
                log.error('CAPTCHA detectado em %s (categoria %s).', url, label)
                break

            self.pages_scraped += 1
            page_offers = self._extract_cards(html)
            captured: list[tuple[str, int, float]] = []
            for offer in page_offers:
                offer.source_label = label
                data = offer.to_dict()
                if category_code and trust_hint:
                    data['category_hint'] = category_code
                if provenance:
                    data['search_provenance'] = provenance
                if data['id'] in seen_ids:
                    continue
                seen_ids.add(data['id'])
                all_offers.append(data)
                captured.append((data['nome'], data['desconto_pct'], data['preco']))

            log.info(
                '[%s] %d cards | %d novas no ciclo | total acumulado: %d',
                label, len(page_offers), len(captured), len(all_offers),
            )
            for nome, desc, preco in captured:
                log.info('  • [%s] %d%% — R$ %.2f — %s', label, desc, preco, nome[:90])

            if idx < total - 1:
                time.sleep(round(random.uniform(DELAY_MIN, DELAY_MAX), 2))

        return all_offers

    def _extract_cards(self, html: str) -> list['AmazonOffer']:
        soup = BeautifulSoup(html, 'html.parser')

        # fallback 1: cards dcl-product (ofertasmensais e páginas de evento)
        items = soup.select('div.dcl-product')

        # fallback 2: itens de resultado de busca com data-asin (goldbox/deals)
        if not items:
            items = [el for el in soup.select('[data-asin]') if el.get('data-asin', '').strip()]

        # fallback 3: resultados de busca padrão do Amazon Search
        if not items:
            items = soup.select('[data-component-type="s-search-result"]')

        log.info('%d cards Amazon encontrados', len(items))
        offers = []
        for card in items:
            offer = self._parse_item(card)
            if offer:
                offers.append(offer)
        return offers

    def _parse_item(self, card) -> Optional['AmazonOffer']:
        try:
            # ASIN — 3 níveis de fallback
            # fallback 1: href do link principal do produto (dcl-product-link)
            asin = ''
            link_el = card.select_one('a.dcl-product-link, a[href*="/dp/"]')
            if link_el:
                m = ASIN_RE.search(link_el.get('href', ''))
                if m:
                    asin = m.group(1)

            # fallback 2: atributo data-asin no próprio card
            if not asin or len(asin) != 10:
                asin = (card.get('data-asin') or '').strip()

            # fallback 3: varredura em todos os hrefs internos
            if not asin or len(asin) != 10:
                for tag in card.find_all(href=True):
                    m = ASIN_RE.search(tag.get('href', ''))
                    if m:
                        asin = m.group(1)
                        break

            if not asin or len(asin) != 10:
                return None

            product_url = f'https://www.amazon.com.br/dp/{asin}'

            # Título — 3 níveis de fallback
            # fallback 1: alt da imagem principal do produto (dcl-dynamic-image)
            img_el = card.select_one('img.dcl-dynamic-image, img.a-dynamic-image, img.s-image')
            title = img_el.get('alt', '').strip() if img_el else ''

            # fallback 2: span de título visível
            if not title:
                title_el = (
                    card.select_one('.a-size-medium.a-color-base.a-text-normal')
                    or card.select_one('.a-size-base-plus.a-color-base.a-text-normal')
                    or card.select_one('span[class*="product-title"]')
                )
                title = title_el.get_text(strip=True) if title_el else ''

            # fallback 3: texto do link do produto
            if not title and link_el:
                title = link_el.get_text(strip=True)

            if not title:
                return None

            # Preço atual — fallbacks por especificidade.
            # Atenção: em resultados de busca, .a-price aparece também no preço
            # por unidade (ex.: "R$ 149,50/L"). Por isso preferimos sempre o
            # elemento com data-a-color="base" e ignoramos data-a-strike="true".
            price = 0.0
            # fallback 1: span.dcl-product-price-new (ofertasmensais)
            price_el = card.select_one('span.dcl-product-price-new .a-offscreen')
            if price_el:
                price = self._parse_brl(price_el.get_text(strip=True))

            # fallback 2: preço marcado como base (search/goldbox/deals)
            if price <= 0:
                price_el = card.select_one('span.a-price[data-a-color="base"] .a-offscreen')
                if price_el:
                    price = self._parse_brl(price_el.get_text(strip=True))

            # fallback 3: primeiro .a-price que NÃO é strike (sem data-a-color)
            if price <= 0:
                for el in card.select('span.a-price'):
                    if el.get('data-a-strike') == 'true':
                        continue
                    if el.get('data-a-color') == 'secondary':
                        continue
                    off = el.select_one('.a-offscreen')
                    if off:
                        candidate = self._parse_brl(off.get_text(strip=True))
                        if candidate > 0:
                            price = candidate
                            break

            # fallback 4: inteiro + fração separados
            if price <= 0:
                whole = card.select_one('.a-price-whole')
                frac = card.select_one('.a-price-fraction')
                if whole:
                    w = re.sub(r'[^0-9]', '', whole.get_text())
                    f = re.sub(r'[^0-9]', '', frac.get_text()) if frac else '00'
                    try:
                        price = float(f'{w}.{f[:2]}')
                    except ValueError:
                        pass

            if price <= 0:
                return None

            # Preço original — só aceitamos quando há sinal explícito de
            # strikethrough. data-a-color="secondary" sozinho é ambíguo:
            # casa também preço por unidade (R$/Kg, R$/L), o que gera
            # descontos fantasma (ex.: banana 180g → R$66/Kg → "82% off").
            original_price = price
            # fallback 1: span.dcl-product-price-old (ofertasmensais)
            orig_el = card.select_one('span.dcl-product-price-old .a-offscreen')
            # fallback 2: preço com strikethrough explícito (search/goldbox/deals)
            if not orig_el:
                orig_el = card.select_one('span.a-price[data-a-strike="true"] .a-offscreen')
            # fallback 3: classes legadas de preço riscado
            if not orig_el:
                orig_el = card.select_one('.a-text-strike .a-offscreen, [class*="was-price"] .a-offscreen')

            if orig_el:
                parsed = self._parse_brl(orig_el.get_text(strip=True))
                if parsed > price:
                    original_price = parsed

            # Percentual de desconto — preferimos o badge da página em vez de calcular.
            discount_pct = 0
            # fallback 1: badge dcl (ofertasmensais) — e.g. "19% off"
            badge_el = card.select_one('div.dcl-badge span.a-size-mini, ._badgeLabel_f6hz5_1 span')
            if badge_el:
                m = re.search(r'(\d+)', badge_el.get_text())
                if m:
                    discount_pct = int(m.group(1))

            # fallback 2: badge "-13%" do search Amazon (savingsPercentage)
            if discount_pct == 0:
                badge_el = card.select_one('span.savingsPercentage, span[class*="savingsPercentage"]')
                if badge_el:
                    m = re.search(r'(\d+)', badge_el.get_text())
                    if m:
                        discount_pct = int(m.group(1))

            # fallback 3: badge genérico de desconto
            if discount_pct == 0:
                badge_el = card.select_one('.a-badge-text, [class*="discount-badge"]')
                if badge_el:
                    m = re.search(r'(\d+)\s*%', badge_el.get_text())
                    if m:
                        discount_pct = int(m.group(1))

            # fallback 4: cálculo a partir dos preços (último recurso)
            if discount_pct == 0 and original_price > price:
                discount_pct = round((original_price - price) / original_price * 100)

            # Guarda anti-fantasma: badges como "savingsPercentage" podem
            # aparecer em variantes/promos que não se refletem no preço avulso.
            # Sem um preço riscado para sustentar o desconto, descartamos.
            if discount_pct > 0 and original_price <= price:
                discount_pct = 0

            if discount_pct < MIN_DISCOUNT:
                return None

            # Imagem
            image = ''
            if img_el:
                image = img_el.get('src') or img_el.get('data-src', '')

            # Prime / frete grátis
            prime_el = card.select_one(
                '[aria-label*="Prime"], .a-icon-prime, [class*="prime-logo"], [class*="primeLogo"]'
            )
            has_free_shipping = bool(prime_el)

            # Vendedor / marca (não exposto em cards de evento — usar padrão)
            seller = 'Amazon.com.br'

            # Rating e quantidade de avaliações — listagem expõe sem requests extras.
            review_rating, review_count = self._extract_reviews(card)

            return AmazonOffer(
                id=asin,
                nome=title,
                preco=price,
                preco_original=original_price,
                desconto_pct=discount_pct,
                link_direto=product_url,
                link_afiliado=self._build_affiliate_url(product_url, asin),
                imagem=image,
                vendedor=seller,
                condicao='Novo',
                frete_gratis=has_free_shipping,
                data=datetime.now(timezone(BRT_OFFSET)).strftime('%Y-%m-%d'),
                review_rating=review_rating,
                review_count=review_count,
            )
        except Exception as exc:
            log.debug('Erro ao parsear card Amazon: %s', exc)
            return None

    def _extract_reviews(self, card) -> tuple[float, int]:
        # Nota média — texto "4,5 de 5 estrelas" em .a-icon-alt
        rating = 0.0
        rating_el = card.select_one('i.a-icon-star-small .a-icon-alt, i.a-icon-star .a-icon-alt, .a-icon-alt')
        if rating_el:
            m = re.search(r'(\d+[\.,]\d+)', rating_el.get_text())
            if m:
                try:
                    rating = float(m.group(1).replace(',', '.'))
                    if rating < 0 or rating > 5:
                        rating = 0.0
                except ValueError:
                    rating = 0.0

        # Quantidade — span perto do rating, ex "(1.234)" ou número solto
        count = 0
        count_el = card.select_one('.a-size-base.s-underline-text, .s-underline-link-text, .a-link-normal .a-size-base')
        if count_el:
            text = re.sub(r'[^\d]', '', count_el.get_text())
            if text:
                try:
                    count = int(text)
                except ValueError:
                    count = 0

        return rating, count

    def _parse_brl(self, text: str) -> float:
        text = re.sub(r'[R$\s\xa0]', '', text)
        if ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return 0.0

    def _build_affiliate_url(self, product_url: str, asin: str) -> str:
        if not self.associate_tag:
            return product_url

        link_id = hashlib.md5(f'{asin}:{self.associate_tag}'.encode('utf-8')).hexdigest()
        query = urllib.parse.urlencode(
            {
                'th': '1',
                'linkCode': 'sl2',
                'tag': self.associate_tag,
                'linkId': link_id,
            },
        )
        return f'{product_url}?{query}'


def build_from_env() -> AmazonScraper:
    return AmazonScraper(
        associate_tag=(
            os.environ.get('AMAZON_AFFILIATE_TAG')
            or os.environ.get('AMAZON_ASSOCIATE_TAG', '')
        ),
    )
