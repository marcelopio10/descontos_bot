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
from scrapers.base import HTTP_EXCEPTIONS, BaseScraper, build_impersonated_session

log = logging.getLogger(__name__)

BRT_OFFSET = timedelta(hours=-3)
MAX_PAGES = 5
MIN_DISCOUNT = 5
DELAY_MIN = 2.0
DELAY_MAX = 4.5


def _normalize_for_match(value: str) -> str:
    """Forma canônica para casar título de `og:title` com título de card."""
    folded = unicodedata.normalize('NFKD', value or '')
    folded = ''.join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', folded).strip().lower()


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
        except HTTP_EXCEPTIONS as exc:
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

            if self.is_blocked(html):
                self.blocked = True
                self.error_message = f'CAPTCHA detectado em {url}'
                log.error('CAPTCHA detectado em %s (categoria %s).', url, label)
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
        if self.is_blocked(html):
            self.blocked = True
            self.error_message = f'CAPTCHA detectado em {url}'
            log.error('CAPTCHA detectado ao resolver vitrine social %s.', url)
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
            log.debug('Erro ao parsear card: %s', exc)
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
        if not permalink:
            return permalink
        if not self.ml_cookie or not self.ml_csrf or not self.affiliate_tag:
            self._exibir_alerta_cookie(motivo='credenciais_nao_configuradas')
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
            # Sessão dedicada, isolada de `self.session` (achado 2026-07-22): a
            # sessão de raspagem acumula cookies novos a cada página de listagem
            # visitada — inclusive um `_csrf` fresco do próprio Mercado Livre, que
            # não bate mais com o `ML_CSRF_TOKEN` estático do `.env`. Reusar
            # `self.session.post` aqui mescla esse cookie novo por cima do
            # `cookie` explícito acima, quebrando o CSRF e derrubando a chamada em
            # 401/403 mesmo com credenciais válidas — isolado numa sessão nova,
            # sem esse acúmulo, a mesma credencial funciona de forma consistente.
            resp = build_impersonated_session('chrome124').post(url_api, headers=headers, json=data, timeout=10)
            if resp.ok:
                return resp.json().get('short_url', permalink)
            if resp.status_code in (401, 403):
                self._exibir_alerta_cookie(motivo=f'rejeitado_pelo_ml_http_{resp.status_code}')
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
