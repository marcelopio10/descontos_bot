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
    from curl_cffi import requests as cffi_requests
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as cffi_requests  # fallback; pode falhar em TLS fingerprinting
    _CURL_CFFI_AVAILABLE = False
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=True)
except ImportError:
    pass

log = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)
MIN_DISCOUNT = 5
DELAY_MIN = 3.0
DELAY_MAX = 6.0

ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})')

# Páginas de ofertas da Amazon — scrapeadas em ordem até max_pages
DEAL_URLS = [
    'https://www.amazon.com.br/events/ofertasmensais?ref_=nav_cs_gb',
    'https://www.amazon.com.br/deals',
    'https://www.amazon.com.br/gp/goldbox',
    'https://www.amazon.com.br/s?i=aps&deal-type=eligible&rh=n%3A1229514011',   # Eletrônicos
    'https://www.amazon.com.br/s?i=aps&deal-type=eligible&rh=n%3A14617390011',  # Esporte e lazer
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
        }


class AmazonScraper:
    """
    Scraper de ofertas Amazon.com.br usando curl-cffi (impersona TLS do Chrome
    para contornar bloqueio anti-bot que rejeita o requests padrão com HTTP 503).
    """

    def __init__(self, associate_tag: str = ''):
        self.associate_tag = associate_tag
        self.today = datetime.now(timezone(BRT_OFFSET)).date()
        self.pages_scraped = 0
        self.blocked = False
        self.error_message = ''
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Upgrade-Insecure-Requests': '1',
        }
        if _CURL_CFFI_AVAILABLE:
            self.session = cffi_requests.Session(impersonate='chrome124')
        else:
            log.warning('curl_cffi não disponível — usando requests padrão (Amazon pode bloquear por TLS).')
            self.session = cffi_requests.Session()

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
        for attempt, backoff in enumerate([0, 2, 4, 8], start=1):
            if backoff:
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

    def scrape_daily_deals(self, max_pages: int = 5) -> list[dict]:
        all_offers: list[dict] = []
        seen_ids: set[str] = set()
        urls = DEAL_URLS[:max_pages]

        for idx, url in enumerate(urls):
            if self.blocked:
                break

            log.info('Buscando ofertas Amazon (%d/%d): %s', idx + 1, len(urls), url)
            html = self.get_html(url)
            if not html:
                continue

            if self.is_blocked(html):
                self.blocked = True
                self.error_message = f'CAPTCHA detectado em {url}'
                log.error('CAPTCHA detectado em %s.', url)
                break

            self.pages_scraped += 1
            page_offers = self._extract_cards(html)
            new_on_page = 0
            for offer in page_offers:
                data = offer.to_dict()
                if data['id'] not in seen_ids:
                    seen_ids.add(data['id'])
                    all_offers.append(data)
                    new_on_page += 1

            log.info('Página %d: %d novas | total acumulado: %d', idx + 1, new_on_page, len(all_offers))

            if idx < len(urls) - 1:
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

            # Preço atual — 3 níveis de fallback
            # fallback 1: span.dcl-product-price-new .a-offscreen (ofertasmensais)
            price = 0.0
            price_el = card.select_one('span.dcl-product-price-new .a-offscreen')
            if price_el:
                price = self._parse_brl(price_el.get_text(strip=True))

            # fallback 2: qualquer .a-price .a-offscreen no card
            if price <= 0:
                price_el = card.select_one('.a-price .a-offscreen')
                if price_el:
                    price = self._parse_brl(price_el.get_text(strip=True))

            # fallback 3: inteiro + fração separados
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

            # Preço original — 3 níveis de fallback
            original_price = price
            # fallback 1: span.dcl-product-price-old .a-offscreen (ofertasmensais)
            orig_el = card.select_one('span.dcl-product-price-old .a-offscreen')
            if not orig_el:
                # fallback 2: .a-text-price .a-offscreen (goldbox/deals)
                orig_el = card.select_one('.a-text-price .a-offscreen')
            if not orig_el:
                # fallback 3: qualquer preço riscado
                orig_el = card.select_one('.a-text-strike, [class*="was-price"] .a-offscreen')

            if orig_el:
                parsed = self._parse_brl(orig_el.get_text(strip=True))
                if parsed > price:
                    original_price = parsed

            # Percentual de desconto — 3 níveis de fallback
            discount_pct = 0
            # fallback 1: badge dcl (ofertasmensais) — e.g. "19% off"
            badge_el = card.select_one('div.dcl-badge span.a-size-mini, ._badgeLabel_f6hz5_1 span')
            if badge_el:
                m = re.search(r'(\d+)', badge_el.get_text())
                if m:
                    discount_pct = int(m.group(1))

            # fallback 2: badge genérico de desconto
            if discount_pct == 0:
                badge_el = card.select_one('.a-badge-text, [class*="discount-badge"]')
                if badge_el:
                    m = re.search(r'(\d+)\s*%', badge_el.get_text())
                    if m:
                        discount_pct = int(m.group(1))

            # fallback 3: cálculo a partir dos preços
            if discount_pct == 0 and original_price > price:
                discount_pct = round((original_price - price) / original_price * 100)

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
            )
        except Exception as exc:
            log.debug('Erro ao parsear card Amazon: %s', exc)
            return None

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
        associate_tag=os.environ.get('AMAZON_ASSOCIATE_TAG', ''),
    )
