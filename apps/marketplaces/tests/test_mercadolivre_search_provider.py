from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.mercadolivre_api_client import MercadoLivreApiError
from apps.marketplaces.services.mercadolivre_search_provider import MercadoLivreSearchProvider
from apps.marketplaces.services.search_provenance import (
    build_sanitized_raw_payload,
    sanitize_search_provenance,
)


class FakeClient:
    def __init__(self):
        self.search_calls = []
        self.item_calls = []

    def get(self, path, *, params=None):
        self.search_calls.append((path, params))
        offset = int((params or {}).get('offset', 0))
        if offset == 0:
            return {'paging': {'total': 3, 'offset': 0, 'limit': 2}, 'results': ['MLB1', 'MLB2']}
        return {'paging': {'total': 3, 'offset': 2, 'limit': 2}, 'results': ['MLB3']}

    def get_items(self, item_ids):
        self.item_calls.append(list(item_ids))
        return [
            {'status_code': 200, 'id': item_id, 'body': {'title': f'Produto {item_id}', 'status': 'active'}}
            for item_id in item_ids
        ]


class PartialClient(FakeClient):
    def get_items(self, item_ids):
        self.item_calls.append(list(item_ids))
        result = []
        for item_id in item_ids:
            if item_id == 'MLB404':
                result.append({'status_code': 404, 'id': item_id, 'body': {}})
            else:
                result.append({'status_code': 200, 'id': item_id, 'body': {'title': 'Produto'}})
        return result


class MercadoLivreSearchProviderTests(SimpleTestCase):
    def test_paginates_deduplicates_and_hydrates_items(self):
        client = FakeClient()
        provider = MercadoLivreSearchProvider(client, page_size=2)

        result = provider.search(
            query_text='cafeteira',
            category_id='MLB1574',
            sort='price_asc',
            max_pages=2,
            provenance={'source_kind': 'radar_brand', 'category_code': 'casa_cozinha'},
        )

        self.assertEqual([item['id'] for item in result], ['MLB1', 'MLB2', 'MLB3'])
        self.assertEqual(len(client.search_calls), 2)
        self.assertEqual(client.search_calls[0][1]['q'], 'cafeteira')
        self.assertEqual(client.search_calls[0][1]['category'], 'MLB1574')
        self.assertEqual(client.search_calls[0][1]['sort'], 'price_asc')
        self.assertEqual(client.item_calls, [['MLB1', 'MLB2', 'MLB3']])
        self.assertEqual(result[0]['_category_hint'], 'casa_cozinha')

    def test_search_many_merges_provenance_for_duplicate_item(self):
        client = FakeClient()
        provider = MercadoLivreSearchProvider(client, page_size=50)
        result = provider.search_many([
            {'query_text': 'cafeteira', 'category_id': '', 'sort': '', 'provenance': {'source_kind': 'radar_brand'}},
            {'query_text': '', 'category_id': 'MLB1574', 'sort': '', 'provenance': {'category_code': 'casa_cozinha'}},
        ], max_pages=1)

        self.assertEqual([item['id'] for item in result], ['MLB1', 'MLB2'])
        self.assertEqual(result[0]['_search_provenance']['source_kind'], 'radar_brand')
        self.assertEqual(result[0]['_search_provenance']['category_code'], 'casa_cozinha')
        self.assertEqual(client.item_calls, [['MLB1', 'MLB2']])

    def test_untrusted_category_does_not_become_classifier_hint(self):
        client = FakeClient()
        result = MercadoLivreSearchProvider(client).search(
            category_id='MLB1430',
            max_pages=1,
            provenance={
                'source_kind': 'category_target',
                'category_code': 'moda_feminina',
                'trust_hint': 'false',
            },
        )
        self.assertEqual(result[0]['_category_code'], 'moda_feminina')
        self.assertEqual(result[0]['_category_hint'], '')

    def test_bulk_404_is_returned_for_audit(self):
        client = PartialClient()
        client.get = lambda path, params=None: {
            'paging': {'total': 2, 'offset': 0, 'limit': 2},
            'results': ['MLB404', 'MLB1'],
        }
        result = MercadoLivreSearchProvider(client).search(max_pages=1)
        self.assertEqual(result[0]['_api_error'], 404)
        self.assertEqual(result[0]['id'], 'MLB404')

    @override_settings(ML_API_SITE_ID='MLA')
    def test_rejects_non_mlb_site(self):
        with self.assertRaises(MercadoLivreApiError):
            MercadoLivreSearchProvider(FakeClient()).search(max_pages=1)

    def test_rejects_invalid_search_schema(self):
        payloads = (
            {'paging': {'total': 1, 'offset': 0, 'limit': 2}, 'results': {'id': 'MLB1'}},
            {'paging': {'total': '1', 'offset': 0, 'limit': 2}, 'results': ['MLB1']},
            {'paging': {'total': 3, 'offset': 0, 'limit': 2}, 'results': ['MLB1']},
            {'paging': {'total': 2, 'offset': 0, 'limit': 2}, 'results': ['MLB1', 'MLB1']},
            {'paging': {'total': 1, 'offset': 0, 'limit': 2}, 'results': ['MLBABC']},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                client = FakeClient()
                client.get = lambda path, params=None, payload=payload: payload
                with self.assertRaises(MercadoLivreApiError):
                    MercadoLivreSearchProvider(client, page_size=2).search(max_pages=1)

    def test_sanitizes_case_insensitive_urls_jids_and_sensitive_keys(self):
        result = sanitize_search_provenance({
            'source_kind': 'RADAR_BRAND',
            'query_text': 'HTTPS://evil.example/secret',
            'brand': 'HTTP://evil.example/secret',
            'marketplace': '123@G.US',
        })
        safe_payload = build_sanitized_raw_payload({
            'title': 'Produto',
            'RAW_TEXT': 'secret',
            'Group_JID': '123@g.us',
            'SENDER_HASH': 'secret',
            'EXTERNAL_MESSAGE_ID': 'secret',
        })

        self.assertEqual(result, {'source_kind': 'radar_brand'})
        self.assertEqual(safe_payload, {'title': 'Produto'})
