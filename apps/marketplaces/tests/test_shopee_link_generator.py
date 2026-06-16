from django.test import SimpleTestCase

from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateError
from apps.marketplaces.services.shopee_link_generator import (
    build_sub_ids,
    generate_short_link,
    resolve_affiliate_link,
)


class FakeClient:
    def __init__(self, data=None, raise_exc=None):
        self.data = data
        self.raise_exc = raise_exc
        self.calls = []

    def execute(self, query, variables=None):
        self.calls.append((query, variables))
        if self.raise_exc:
            raise self.raise_exc
        return self.data


class LinkGeneratorTests(SimpleTestCase):
    def test_build_sub_ids_order(self):
        self.assertEqual(
            build_sub_ids('telegram', 'achadinhos', 'eletronicos', '2026-06-14'),
            ['descontosbot', 'telegram', 'achadinhos', 'eletronicos', '2026-06-14'],
        )

    def test_resolve_prefers_offer_link(self):
        client = FakeClient()
        link = resolve_affiliate_link(
            {'offerLink': 'https://s.shopee.com.br/abc', 'productLink': 'https://shopee.com.br/p/1'},
            client=client,
        )
        self.assertEqual(link, 'https://s.shopee.com.br/abc')
        self.assertEqual(client.calls, [])  # não chamou a API

    def test_resolve_generates_short_link_when_no_offer_link(self):
        client = FakeClient(data={'generateShortLink': {'shortLink': 'https://s.shopee.com.br/gen'}})
        link = resolve_affiliate_link(
            {'productLink': 'https://shopee.com.br/p/1'},
            channel_code='whatsapp',
            client=client,
        )
        self.assertEqual(link, 'https://s.shopee.com.br/gen')
        _query, variables = client.calls[0]
        self.assertEqual(variables['input']['originUrl'], 'https://shopee.com.br/p/1')
        self.assertEqual(variables['input']['subIds'][1], 'whatsapp')

    def test_generate_short_link_requires_short_link_in_response(self):
        client = FakeClient(data={'generateShortLink': {}})
        with self.assertRaises(ShopeeAffiliateError):
            generate_short_link('https://shopee.com.br/p/1', build_sub_ids(), client=client)
