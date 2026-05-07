#!/usr/bin/env python3
import json
import sys
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / 'site'
DISCLOSURE = 'Como Associado da Amazon, ganho por compras qualificadas.'
AMAZON_TAG = 'descontos.bot-20'
PROHIBITED_TEXTS = [
    'compre aqui e ganhe desconto exclusivo',
    'cashback',
    'doação por compra',
    'favorite este link',
    'cupom exclusivo Amazon',
    'imitação',
    'réplica',
]


class ComplianceError(Exception):
    pass


def main() -> int:
    try:
        with local_site_server() as base_url:
            check_home(base_url)
            offers = check_offers_json(base_url)
            check_offer_page(base_url, offers)
            check_links_json(base_url)
            check_links_page(base_url)
    except ComplianceError as exc:
        print(f'COMPLIANCE CHECK FAILED: {exc}', file=sys.stderr)
        return 1

    print('ALL COMPLIANCE CHECKS PASSED')
    return 0


def check_home(base_url: str) -> None:
    html = fetch_text(base_url, '/')
    assert_contains(html, DISCLOSURE, 'Home sem disclosure Amazon.')
    assert_no_prohibited_text(html, 'Home')


def check_offers_json(base_url: str) -> list[dict]:
    payload = fetch_json(base_url, '/offers.json')
    if payload.get('disclosure') != DISCLOSURE:
        raise ComplianceError('offers.json sem disclosure canônico.')

    offers = payload.get('offers')
    if not isinstance(offers, list) or not offers:
        raise ComplianceError('offers.json sem lista de ofertas.')

    for offer in offers:
        title = offer.get('title', 'oferta sem título')
        assert_no_prohibited_text(json.dumps(offer, ensure_ascii=False), title)
        affiliate_link = offer.get('affiliate_link', '')
        marketplace = offer.get('marketplace') or {}
        is_amazon_offer = marketplace.get('code') == 'amazon'
        if is_amazon_offer and not affiliate_link:
            raise ComplianceError(f'Oferta "{title}" sem affiliate_link.')
        if (
            (is_amazon_offer or is_amazon_url(affiliate_link))
            and not has_valid_amazon_tag(affiliate_link)
        ):
            raise ComplianceError(f'Oferta "{title}" sem tag Amazon correta.')
        if not offer.get('slug'):
            raise ComplianceError(f'Oferta "{title}" sem slug.')

    return offers


def check_offer_page(base_url: str, offers: list[dict]) -> None:
    first_offer = offers[0]
    if not first_offer.get('price_collected_at'):
        raise ComplianceError('Primeira oferta de offers.json sem price_collected_at.')
    if not first_offer.get('slug'):
        raise ComplianceError('Primeira oferta de offers.json sem slug.')

    slug = quote(first_offer['slug'])
    html = fetch_text(base_url, f'/oferta.html?slug={slug}')
    javascript = read_site_text('assets/site.js')
    assert_contains(html, DISCLOSURE, 'oferta.html sem disclosure no HTML estático.')
    assert_contains(
        javascript,
        'Preço coletado em',
        'oferta.html sem timestamp de preço renderizado.',
    )


def check_links_json(base_url: str) -> None:
    payload = fetch_json(base_url, '/links.json')
    if payload.get('disclosure') != DISCLOSURE:
        raise ComplianceError('links.json sem disclosure canônico.')

    items = payload.get('items')
    if not isinstance(items, list) or len(items) < 5:
        raise ComplianceError('links.json precisa ter pelo menos 5 itens.')

    for item in items:
        title = item.get('title', 'link sem título')
        tracked_url = item.get('tracked_url', '')
        if not tracked_url:
            raise ComplianceError(f'Link "{title}" sem tracked_url.')
        query = parse_qs(urlparse(tracked_url).query)
        if query.get('utm_source') != ['instagram']:
            raise ComplianceError(f'Link "{title}" sem utm_source=instagram.')
        if query.get('utm_medium') != ['bio']:
            raise ComplianceError(f'Link "{title}" sem utm_medium=bio.')
        if is_amazon_url(tracked_url) and not has_valid_amazon_tag(tracked_url):
            raise ComplianceError(
                f'Link "{title}" sem tag Amazon correta.',
            )


def check_links_page(base_url: str) -> None:
    try:
        html = fetch_text(base_url, '/links')
    except ComplianceError:
        html = fetch_text(base_url, '/links.html')
    assert_contains(html, DISCLOSURE, '/links.html sem disclosure Amazon.')
    assert_no_prohibited_text(html, '/links.html')


@contextmanager
def local_site_server():
    handler = partial(QuietHTTPRequestHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f'http://{host}:{port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args) -> None:
        return


def fetch_text(base_url: str, path: str) -> str:
    url = f'{base_url}{path}'
    try:
        with urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise ComplianceError(f'{path} retornou HTTP {response.status}.')
            return response.read().decode('utf-8')
    except HTTPError as exc:
        raise ComplianceError(f'{path} retornou HTTP {exc.code}.') from exc
    except URLError as exc:
        raise ComplianceError(f'{path} não respondeu: {exc.reason}.') from exc


def fetch_json(base_url: str, path: str) -> dict:
    text = fetch_text(base_url, path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComplianceError(f'{path} não é JSON válido: {exc}.') from exc


def read_site_text(relative_path: str) -> str:
    path = SITE_DIR / relative_path
    if not path.exists():
        raise ComplianceError(
            f'{relative_path} não existe; equivalente HTTP 200 falharia.',
        )
    return path.read_text(encoding='utf-8')


def assert_contains(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise ComplianceError(message)


def assert_no_prohibited_text(text: str, context: str) -> None:
    lowered = text.lower()
    for prohibited in PROHIBITED_TEXTS:
        if prohibited.lower() in lowered:
            raise ComplianceError(f'{context} contém texto proibido: {prohibited}.')


def is_amazon_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return (
        host.endswith('amazon.com.br')
        or host.endswith('amzn.to')
        or host.endswith('amzlink.to')
    )


def has_valid_amazon_tag(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host.endswith('amzn.to') or host.endswith('amzlink.to'):
        return True
    query = parse_qs(urlparse(url).query)
    return query.get('tag') == [AMAZON_TAG]


if __name__ == '__main__':
    raise SystemExit(main())
