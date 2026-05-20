import logging
import os
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=True)
except ImportError:
    pass

from scrapers.base import BaseScraper

log = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)
MAX_PAGES = 5
MIN_DISCOUNT = 5
DELAY_MIN = 2.0
DELAY_MAX = 4.5


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
        self.session = requests.Session()

    def get_html(self, url: str) -> str:
        try:
            resp = self.fetch_with_retry(self.session, url, headers=self.headers, timeout=20)
            if resp.status_code == 403:
                self.blocked = True
                self.error_message = f'Acesso negado 403 em {url}'
                log.error('Acesso negado 403. URL: %s', url)
                return ''
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            self.error_message = f'Erro ao acessar {url}: {exc}'
            log.error('Erro ao acessar %s: %s', url, exc)
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

            if self.is_blocked(html):
                self.blocked = True
                self.error_message = f'CAPTCHA detectado na página {page}'
                log.error('CAPTCHA detectado na página %d.', page)
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
            if 'click1.mercadolivre' in permalink or 'mclics' in permalink:
                parsed = urllib.parse.urlparse(permalink)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'url' in qs:
                    permalink = qs['url'][0]

            if '?' in permalink:
                permalink = permalink.split('?')[0]
            if '#' in permalink:
                permalink = permalink.split('#')[0]
            if not permalink or not title:
                return None

            item_id = 'MLB000000000'
            match = re.search(r'(MLB[\-]?\d+)', permalink)
            if match:
                item_id = match.group(1).replace('-', '')
            else:
                fallback_id = ''.join(filter(str.isalnum, title[:20]))
                item_id = f'MLB_{fallback_id}'

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
            )
        except Exception as exc:
            log.debug('Erro ao parsear card: %s', exc)
            return None

    def _exibir_alerta_cookie(self) -> None:
        if getattr(self, '_alerta_exibido', False):
            return
        self._alerta_exibido = True
        log.error(
            'ATENÇÃO: cookie/token do Mercado Livre expirou ou está ausente. '
            'Renove ML_COOKIE e ML_CSRF_TOKEN no .env.'
        )

    def _gerar_link_afiliado_oficial(self, permalink: str) -> str:
        if not permalink:
            return permalink
        if not self.ml_cookie or not self.ml_csrf or not self.affiliate_tag:
            self._exibir_alerta_cookie()
            return permalink

        url_api = 'https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links'
        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'cookie': self.ml_cookie,
            'origin': 'https://www.mercadolivre.com.br',
            'referer': permalink,
            'user-agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/147.0.0.0 Safari/537.36'
            ),
            'x-csrf-token': self.ml_csrf,
        }
        data = {
            'url': permalink,
            'tag': self.affiliate_tag,
        }

        try:
            resp = self.session.post(url_api, headers=headers, json=data, timeout=10)
            if resp.ok:
                return resp.json().get('short_url', permalink)
            if resp.status_code in (401, 403):
                self._exibir_alerta_cookie()
            else:
                log.error('Erro na API de afiliados HTTP %s: %s', resp.status_code, resp.text)
        except Exception as exc:
            log.error('Erro ao gerar link de afiliado oficial: %s', exc)
        return permalink


def build_from_env() -> MercadoLivreScraper:
    return MercadoLivreScraper(
        affiliate_id=os.environ.get('ML_AFFILIATE_ID', ''),
        affiliate_tag=os.environ.get('ML_AFFILIATE_TAG', ''),
        ml_cookie=os.environ.get('ML_COOKIE', ''),
        ml_csrf=os.environ.get('ML_CSRF_TOKEN', ''),
    )
