from typing import cast
from unittest.mock import Mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.mercadolivre_auth import (
    MercadoLivreAuthError,
    MercadoLivreTokenProvider,
    validate_api_configuration,
)


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class SneakyInt(int):
    def __str__(self):
        return 'STATUS_SECRET_SENTINEL'


class MercadoLivreAuthTests(SimpleTestCase):
    def test_refresh_updates_in_memory_tokens_without_logging_secrets(self):
        transport = Mock(return_value=Response(200, {
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
        }))
        provider = MercadoLivreTokenProvider(
            access_token='old-access',
            refresh_token='old-refresh',
            client_id='client',
            client_secret='secret',
            transport=transport,
        )

        self.assertEqual(provider.refresh(), 'new-access')
        self.assertEqual(provider.access_token, 'new-access')
        self.assertEqual(provider.snapshot().refresh_token, 'new-refresh')
        self.assertNotIn('new-access', str(transport.call_args))

    def test_token_snapshot_string_representation_redacts_tokens(self):
        snapshot = MercadoLivreTokenProvider(
            access_token='access-sentinel',
            refresh_token='refresh-sentinel',
        ).snapshot()

        self.assertNotIn('access-sentinel', repr(snapshot))
        self.assertNotIn('refresh-sentinel', repr(snapshot))
        self.assertNotIn('access-sentinel', str(snapshot))
        self.assertNotIn('refresh-sentinel', str(snapshot))

    def test_refresh_network_error_is_sanitized(self):
        provider = MercadoLivreTokenProvider(
            access_token='expired',
            refresh_token='refresh',
            client_id='client',
            client_secret='secret',
            transport=Mock(side_effect=requests.ConnectionError()),
        )
        with self.assertRaises(MercadoLivreAuthError) as context:
            provider.refresh()
        self.assertIn('ConnectionError', str(context.exception))
        self.assertNotIn('secret', str(context.exception))

    def test_missing_access_token_fails_closed(self):
        provider = MercadoLivreTokenProvider(access_token='')
        with self.assertRaises(MercadoLivreAuthError):
            provider.access_token

    def test_non_string_access_token_fails_closed(self):
        provider = MercadoLivreTokenProvider(access_token=123)
        with self.assertRaises(MercadoLivreAuthError):
            provider.access_token

    def test_missing_api_credentials_fail_closed(self):
        provider = MercadoLivreTokenProvider(
            access_token='',
            refresh_token='',
            client_id='',
            client_secret='',
        )
        with self.assertRaises(MercadoLivreAuthError):
            provider.access_token

    def test_configuration_validation_rejects_invalid_site_and_base_url(self):
        complete = {
            'ML_API_BASE_URL': 'https://api.mercadolibre.com',
            'ML_API_SITE_ID': 'MLB',
            'ML_API_ACCESS_TOKEN': 'access',
            'ML_API_CLIENT_ID': 'client',
            'ML_API_CLIENT_SECRET': 'client-secret',
            'ML_API_REFRESH_TOKEN': 'refresh',
        }
        for field_name, value in (
            ('ML_API_SITE_ID', 'MLA'),
            ('ML_API_BASE_URL', 'https://api.mercadolibre.com/v1'),
            ('ML_API_BASE_URL', 'https://user:password@api.mercadolibre.com'),
            ('ML_API_BASE_URL', 'https://api.mercadolibre.com:443'),
            ('ML_API_BASE_URL', 'https://api.mercadolibre.com?'),
            ('ML_API_BASE_URL', 'https://api.mercadolibre.com#'),
            ('ML_API_BASE_URL', '\nhttps://api.mercadolibre.com'),
        ):
            with self.subTest(field_name=field_name, value=value):
                with self.settings(**{**complete, field_name: value}):
                    with self.assertRaises(MercadoLivreAuthError):
                        validate_api_configuration()

    @override_settings(ML_API_ACCESS_TOKEN='   ')
    def test_whitespace_access_token_fails_closed(self):
        provider = MercadoLivreTokenProvider()
        with self.assertRaises(MercadoLivreAuthError):
            provider.access_token

    def test_configuration_validation_reports_each_missing_field(self):
        complete = {
            'ML_API_BASE_URL': 'https://api.mercadolibre.com',
            'ML_API_SITE_ID': 'MLB',
            'ML_API_ACCESS_TOKEN': 'access',
            'ML_API_CLIENT_ID': 'client',
            'ML_API_CLIENT_SECRET': 'client-secret',
            'ML_API_REFRESH_TOKEN': 'refresh',
        }
        for field_name in complete:
            with self.subTest(field_name=field_name):
                values = {**complete, field_name: ''}
                with self.settings(**values):
                    with self.assertRaises(MercadoLivreAuthError) as context:
                        validate_api_configuration()
                self.assertIn(field_name, str(context.exception))
                self.assertNotIn('client-secret', str(context.exception))

    def test_configuration_validation_rejects_non_string_credentials(self):
        complete = {
            'ML_API_BASE_URL': 'https://api.mercadolibre.com',
            'ML_API_SITE_ID': 'MLB',
            'ML_API_ACCESS_TOKEN': 'access',
            'ML_API_CLIENT_ID': 'client',
            'ML_API_CLIENT_SECRET': 'client-secret',
            'ML_API_REFRESH_TOKEN': 'refresh',
        }
        for field_name in (
            'ML_API_ACCESS_TOKEN',
            'ML_API_CLIENT_ID',
            'ML_API_CLIENT_SECRET',
            'ML_API_REFRESH_TOKEN',
        ):
            with self.subTest(field_name=field_name):
                with self.settings(**{**complete, field_name: 123}):
                    with self.assertRaises(MercadoLivreAuthError):
                        validate_api_configuration()

    def test_refresh_requires_complete_credentials(self):
        provider = MercadoLivreTokenProvider(
            access_token='old-access',
            refresh_token='old-refresh',
        )
        with self.assertRaises(MercadoLivreAuthError):
            provider.refresh()

    def test_refresh_rejects_non_string_credentials_before_transport(self):
        for field_name in ('refresh_token', 'client_id', 'client_secret'):
            with self.subTest(field_name=field_name):
                transport = Mock()
                values = {
                    'access_token': 'old-access',
                    'refresh_token': 'old-refresh',
                    'client_id': 'client',
                    'client_secret': 'client-secret',
                    field_name: 123,
                    'transport': transport,
                }
                provider = MercadoLivreTokenProvider(**values)

                with self.assertRaises(MercadoLivreAuthError):
                    provider.refresh()

                transport.assert_not_called()
                self.assertEqual(provider.access_token, 'old-access')

    @override_settings(ML_API_BASE_URL='https://api.mercadolibre.com/v1')
    def test_refresh_rejects_invalid_api_origin_before_transport(self):
        transport = Mock()
        provider = MercadoLivreTokenProvider(
            access_token='old-access',
            refresh_token='old-refresh',
            client_id='client',
            client_secret='client-secret',
            transport=transport,
        )

        with self.assertRaises(MercadoLivreAuthError):
            provider.refresh()

        transport.assert_not_called()

    def test_refresh_does_not_follow_redirects(self):
        transport = Mock(return_value=Response(307, {'location': 'https://evil.example'}))
        provider = MercadoLivreTokenProvider(
            access_token='old-access',
            refresh_token='old-refresh',
            client_id='client',
            client_secret='client-secret',
            transport=transport,
        )

        with self.assertRaises(MercadoLivreAuthError):
            provider.refresh()

        self.assertFalse(transport.call_args.kwargs['allow_redirects'])

    def test_refresh_rejects_non_integer_http_status_without_leaking_value(self):
        for status_code in ('secret-sentinel', True, 200.5, SneakyInt(400), 999):
            with self.subTest(status_code=status_code):
                provider = MercadoLivreTokenProvider(
                    access_token='old-access',
                    refresh_token='old-refresh',
                    client_id='client',
                    client_secret='client-secret',
                    transport=Mock(return_value=Response(cast(int, status_code))),
                )

                with self.assertRaises(MercadoLivreAuthError) as context:
                    provider.refresh()

                self.assertNotIn('secret-sentinel', str(context.exception))
                self.assertIsNone(context.exception.__cause__)
                self.assertIsNone(context.exception.__context__)

    def test_refresh_rejects_arbitrary_transport_exception_without_cause(self):
        transport = Mock(side_effect=RuntimeError('secret-sentinel'))
        provider = MercadoLivreTokenProvider(
            access_token='old-access',
            refresh_token='old-refresh',
            client_id='client',
            client_secret='client-secret',
            transport=transport,
        )

        with self.assertRaises(MercadoLivreAuthError) as context:
            provider.refresh()

        self.assertNotIn('secret-sentinel', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    def test_refresh_rejects_non_string_tokens_without_updating_state(self):
        for payload in (
            {'access_token': []},
            {'access_token': 'new-access', 'refresh_token': {}},
            {'access_token': 'new-access', 'refresh_token': True},
        ):
            with self.subTest(payload=payload):
                transport = Mock(return_value=Response(200, payload))
                provider = MercadoLivreTokenProvider(
                    access_token='old-access',
                    refresh_token='old-refresh',
                    client_id='client',
                    client_secret='client-secret',
                    transport=transport,
                )
                with self.assertRaises(MercadoLivreAuthError):
                    provider.refresh()
                self.assertEqual(provider.access_token, 'old-access')
                self.assertEqual(provider.snapshot().refresh_token, 'old-refresh')
