import hashlib

from django.test import SimpleTestCase

from apps.marketplaces.services.shopee_affiliate_client import (
    ShopeeAffiliateClient,
    ShopeeAffiliateError,
    ShopeeConfigError,
    build_auth_header,
    build_signature,
    serialize_payload,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class SignatureTests(SimpleTestCase):
    def test_serialize_payload_is_stable(self):
        a = serialize_payload('query', {'b': 1, 'a': 2})
        b = serialize_payload('query', {'a': 2, 'b': 1})
        self.assertEqual(a, b)

    def test_signature_is_deterministic_and_correct(self):
        sig = build_signature('app', 1000, 'payload', 'secret')
        expected = hashlib.sha256('app1000payloadsecret'.encode('utf-8')).hexdigest()
        self.assertEqual(sig, expected)
        self.assertEqual(sig, build_signature('app', 1000, 'payload', 'secret'))

    def test_auth_header_format(self):
        self.assertEqual(
            build_auth_header('app', 1000, 'sig'),
            'SHA256 Credential=app, Timestamp=1000, Signature=sig',
        )


class ClientExecuteTests(SimpleTestCase):
    def test_missing_credentials_raise_config_error(self):
        client = ShopeeAffiliateClient(app_id='', secret='', transport=lambda *a, **k: None)
        with self.assertRaises(ShopeeConfigError):
            client.execute('query')

    def test_graphql_errors_raise(self):
        def transport(url, data, headers, timeout):
            return FakeResponse({'errors': [{'message': 'boom'}]})

        client = ShopeeAffiliateClient(app_id='a', secret='s', transport=transport, clock=lambda: 1)
        with self.assertRaises(ShopeeAffiliateError):
            client.execute('query')

    def test_signature_covers_sent_payload_without_leaking_secret(self):
        captured = {}

        def transport(url, data, headers, timeout):
            captured['data'] = data
            captured['headers'] = headers
            return FakeResponse({'data': {'ok': 1}})

        client = ShopeeAffiliateClient(
            app_id='app',
            secret='supersecret',
            transport=transport,
            clock=lambda: 1234,
        )
        out = client.execute('query X', {'a': 1})

        self.assertEqual(out, {'ok': 1})
        sent_payload = captured['data'].decode('utf-8')
        expected_sig = build_signature('app', 1234, sent_payload, 'supersecret')
        self.assertIn(expected_sig, captured['headers']['Authorization'])
        self.assertNotIn('supersecret', captured['headers']['Authorization'])

    def test_retry_on_transient_then_success(self):
        calls = {'n': 0}

        def transport(url, data, headers, timeout):
            calls['n'] += 1
            if calls['n'] < 2:
                raise ConnectionError('transient')
            return FakeResponse({'data': {'ok': 1}})

        client = ShopeeAffiliateClient(
            app_id='a',
            secret='s',
            transport=transport,
            clock=lambda: 1,
            sleep=lambda _s: None,
            max_retries=3,
        )
        self.assertEqual(client.execute('query'), {'ok': 1})
        self.assertEqual(calls['n'], 2)

    def test_http_5xx_is_retried_then_fails(self):
        def transport(url, data, headers, timeout):
            return FakeResponse({}, status=503)

        client = ShopeeAffiliateClient(
            app_id='a',
            secret='s',
            transport=transport,
            clock=lambda: 1,
            sleep=lambda _s: None,
            max_retries=2,
        )
        with self.assertRaises(ShopeeAffiliateError):
            client.execute('query')
