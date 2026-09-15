import random
from typing import Any
from unittest.mock import Mock

from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.mercadolivre_api_client import (
    MercadoLivreApiClient,
    MercadoLivreApiError,
)
from apps.marketplaces.services.mercadolivre_auth import (
    MercadoLivreAuthError,
    MercadoLivreTokenProvider,
)


class Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


@override_settings(
    ML_API_ACCESS_TOKEN='access',
    ML_API_CLIENT_ID='client',
    ML_API_CLIENT_SECRET='secret',
    ML_API_REFRESH_TOKEN='refresh',
    ML_API_SITE_ID='MLB',
    ML_API_BASE_URL='https://api.mercadolibre.com',
)
class MercadoLivreApiClientTests(SimpleTestCase):
    def _client(self, responses, *, sleeps=None, provider=None):
        session = Mock()
        session.request.side_effect = list(responses)
        provider = provider or MercadoLivreTokenProvider(access_token='access')
        return MercadoLivreApiClient(
            token_provider=provider,
            transport=session,
            max_retries=3,
            sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
            rng=random.Random(1),
        ), session

    def test_get_retries_429_using_retry_after(self):
        sleeps = []
        client, session = self._client([
            Response(429, headers={'Retry-After': '7'}),
            Response(200, {'ok': True}),
        ], sleeps=sleeps)

        self.assertEqual(client.get('/users/me'), {'ok': True})
        self.assertEqual(sleeps, [7.0])
        self.assertEqual(session.request.call_count, 2)

    @override_settings(
        ML_API_ACCESS_TOKEN='',
        ML_API_CLIENT_ID='',
        ML_API_CLIENT_SECRET='',
        ML_API_REFRESH_TOKEN='',
    )
    def test_incomplete_configuration_never_reaches_transport(self):
        session = Mock()
        client = MercadoLivreApiClient(
            token_provider=MercadoLivreTokenProvider(access_token='access'),
            transport=session,
        )

        with self.assertRaises(MercadoLivreAuthError):
            client.get('/users/me')

        session.request.assert_not_called()

    def test_endpoint_query_and_fragment_are_rejected_before_transport(self):
        session = Mock()
        client = MercadoLivreApiClient(transport=session)

        for path in (
            '/users/me?access_token=sentinel',
            '/users/me#fragment',
            '/../users/me',
            '/%2e%2e/users/me',
            '/..%2fusers/me',
            '/users%2fme',
            '/%252e%252e/users/me',
            '/users/me%253Faccess_token=sentinel',
            '/users%252fme',
        ):
            with self.subTest(path=path):
                with self.assertRaises(MercadoLivreApiError):
                    client.get(path)

        session.request.assert_not_called()

    def test_client_does_not_follow_redirects(self):
        client, session = self._client([Response(307)])

        with self.assertRaises(MercadoLivreApiError):
            client.get('/users/me')

        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    def test_client_rejects_non_integer_http_status(self):
        for status_code in ('200', 200.5, True):
            with self.subTest(status_code=status_code):
                session = Mock()
                response = Mock(status_code=status_code)
                session.request.return_value = response
                client = MercadoLivreApiClient(transport=session)

                with self.assertRaises(MercadoLivreApiError):
                    client.get('/users/me')

                session.request.assert_called_once()

    def test_client_rejects_status_outside_http_range_without_retry(self):
        client, session = self._client([Response(600)])

        with self.assertRaises(MercadoLivreApiError) as context:
            client.get('/users/me')

        self.assertEqual(session.request.call_count, 1)
        self.assertIsNone(context.exception.status_code)
        self.assertFalse(context.exception.retryable)

    def test_get_retries_5xx_with_backoff(self):
        sleeps = []
        client, _session = self._client([
            Response(500),
            Response(200, {'ok': True}),
        ], sleeps=sleeps)

        self.assertEqual(client.get('/users/me'), {'ok': True})
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 1)

    def test_retry_after_invalid_or_huge_values_use_bounded_backoff(self):
        for retry_after in ('١', '9' * 400):
            with self.subTest(retry_after=retry_after):
                sleeps = []
                client, _session = self._client([
                    Response(429, headers={'Retry-After': retry_after}),
                    Response(200, {'ok': True}),
                ], sleeps=sleeps)

                self.assertEqual(client.get('/users/me'), {'ok': True})
                self.assertEqual(len(sleeps), 1)
                self.assertGreaterEqual(sleeps[0], 0)
                self.assertLessEqual(sleeps[0], 8)

    def test_400_403_and_404_are_not_retried(self):
        for status in (400, 403, 404):
            client, session = self._client([Response(status)])
            with self.assertRaises(MercadoLivreApiError) as context:
                client.get('/users/me')
            self.assertEqual(context.exception.status_code, status)
            self.assertEqual(session.request.call_count, 1)

    def test_401_refreshes_once_and_retries(self):
        refresh_transport = Mock(return_value=Response(200, {
            'access_token': 'refreshed',
            'refresh_token': 'refresh-2',
        }))
        provider = MercadoLivreTokenProvider(
            access_token='expired',
            refresh_token='refresh-1',
            client_id='client',
            client_secret='secret',
            transport=refresh_transport,
        )
        client, session = self._client([
            Response(401),
            Response(200, {'ok': True}),
        ], provider=provider)

        self.assertEqual(client.get('/users/me'), {'ok': True})
        self.assertEqual(session.request.call_count, 2)
        refresh_transport.assert_called_once()

    def test_second_401_after_refresh_is_auth_error(self):
        provider = MercadoLivreTokenProvider(
            access_token='expired',
            refresh_token='refresh-1',
            client_id='client',
            client_secret='secret',
            transport=Mock(return_value=Response(200, {'access_token': 'refreshed'})),
        )
        client, _session = self._client(
            [Response(401), Response(401)],
            provider=provider,
        )

        with self.assertRaises(MercadoLivreApiError) as context:
            client.get('/users/me')
        self.assertEqual(context.exception.status_code, 401)
        self.assertTrue(context.exception.auth_error)

    def test_get_items_batches_twenty_ids(self):
        ids = [f'MLB{index}' for index in range(21)]
        first_response = [
            {'status_code': 200, 'id': item_id, 'body': {'id': item_id}}
            for item_id in ids[:20]
        ]
        second_response = [
            {'status_code': 200, 'id': ids[20], 'body': {'id': ids[20]}},
        ]
        client, session = self._client([
            Response(200, first_response),
            Response(200, second_response),
        ])

        result = client.get_items(ids)

        self.assertEqual(len(result), 21)
        self.assertEqual(session.request.call_count, 2)
        self.assertTrue(session.request.call_args_list[0].args[1].endswith('/items/bulk'))
        first_params = session.request.call_args_list[0].kwargs['params']
        second_params = session.request.call_args_list[1].kwargs['params']
        self.assertEqual(len(first_params['ids'].split(',')), 20)
        self.assertEqual(len(second_params['ids'].split(',')), 1)

    def test_get_items_accepts_item_not_found_entry(self):
        client, _session = self._client([
            Response(200, [{'status_code': 404, 'id': 'MLB1'}]),
        ])

        result = client.get_items(['MLB1'])

        self.assertEqual(result, [{'status_code': 404, 'id': 'MLB1'}])

    def test_get_items_rejects_malformed_or_mismatched_bulk_response(self):
        responses = (
            ['not-an-object'],
            [{'status_code': 200, 'id': 'MLB1', 'body': {'id': 'MLB1'}}],
            [
                {'status_code': 200, 'id': 'MLB3', 'body': {'id': 'MLB3'}},
                {'status_code': 200, 'id': 'MLB2', 'body': {'id': 'MLB2'}},
            ],
            [
                {'status_code': 200, 'id': 'MLB1', 'body': {'id': 'MLB1'}},
                {'status_code': 200, 'id': 'MLB1', 'body': {'id': 'MLB1'}},
            ],
            [
                {'status_code': 200, 'id': 'MLB1', 'body': {'id': 'MLB2'}},
                {'status_code': 200, 'id': 'MLB2', 'body': {'id': 'MLB2'}},
            ],
            [
                {'status_code': 200, 'id': 'MLB1'},
                {'status_code': 200, 'id': 'MLB2', 'body': {'id': 'MLB2'}},
            ],
            [
                {'status_code': 302, 'id': 'MLB1'},
                {'status_code': 200, 'id': 'MLB2', 'body': {'id': 'MLB2'}},
            ],
        )
        for response in responses:
            with self.subTest(response=response):
                client, session = self._client([Response(200, response)])
                with self.assertRaises(MercadoLivreApiError):
                    client.get_items(['MLB1', 'MLB2'])
                self.assertEqual(session.request.call_count, 1)

    def test_get_items_rejects_invalid_input_before_any_batch_request(self):
        inputs: tuple[Any, ...] = (
            {'MLB1': True},
            ['MLB1', 'BAD'] + [f'MLB{index}' for index in range(2, 20)],
            [f'MLB{index}' for index in range(20)] + ['MLB19'],
        )
        for item_ids in inputs:
            with self.subTest(item_ids=item_ids):
                session = Mock()
                client = MercadoLivreApiClient(transport=session)
                with self.assertRaises(MercadoLivreApiError):
                    client.get_items(item_ids)
                session.request.assert_not_called()

    def test_item_endpoints_reject_invalid_ids_before_cache_or_transport(self):
        session = Mock()
        client = MercadoLivreApiClient(transport=session)

        for method, args in (
            (client.get_item, ('NOT_AN_MLB_ID',)),
            (client.get_sale_price, ('NOT_AN_MLB_ID', 'channel_marketplace')),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaises(MercadoLivreApiError):
                    method(*args)

        session.request.assert_not_called()

    def test_seller_endpoint_rejects_invalid_ids_before_cache_or_transport(self):
        session = Mock()
        client = MercadoLivreApiClient(transport=session)

        for seller_id in ('BAD', '', '1/../2'):
            with self.subTest(seller_id=seller_id):
                with self.assertRaises(MercadoLivreApiError):
                    client.get_seller(seller_id)

        session.request.assert_not_called()

    def test_item_and_seller_responses_must_match_requested_ids_before_cache(self):
        item_client, item_session = self._client([
            Response(200, {'id': 'MLB999'}),
        ])
        with self.assertRaises(MercadoLivreApiError):
            item_client.get_item('MLB123')
        self.assertNotIn(('item', 'MLB123'), item_client._cache)
        self.assertEqual(item_session.request.call_count, 1)

        seller_client, seller_session = self._client([
            Response(200, {'id': 999}),
        ])
        with self.assertRaises(MercadoLivreApiError):
            seller_client.get_seller('123')
        self.assertNotIn(('seller', '123'), seller_client._cache)
        self.assertEqual(seller_session.request.call_count, 1)

    def test_seller_response_integer_id_matches_string_request(self):
        client, session = self._client([
            Response(200, {'id': 123, 'seller_reputation': {}}),
        ])

        self.assertEqual(client.get_seller('123')['id'], 123)
        self.assertEqual(session.request.call_count, 1)

    def test_client_sanitizes_arbitrary_transport_exception(self):
        session = Mock()
        session.request.side_effect = RuntimeError('secret-sentinel')
        client = MercadoLivreApiClient(transport=session)

        with self.assertRaises(MercadoLivreApiError) as context:
            client.get('/users/me')

        self.assertNotIn('secret-sentinel', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)
