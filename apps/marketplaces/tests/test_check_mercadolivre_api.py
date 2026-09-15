from io import StringIO
from typing import cast
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.marketplaces.services.mercadolivre_api_client import MercadoLivreApiError
from apps.marketplaces.services.mercadolivre_auth import MercadoLivreAuthError


class CheckMercadoLivreApiCommandTests(SimpleTestCase):
    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_success_reports_only_safe_counts(self):
        client = Mock()
        client.get.return_value = {
            'paging': {'total': 1, 'offset': 0, 'limit': 1},
            'results': ['MLB1'],
        }
        out = StringIO()
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            call_command('check_mercadolivre_api', '--limit', '1', stdout=out)
        self.assertIn('Mercado Livre API: OK', out.getvalue())
        self.assertNotIn('Authorization', out.getvalue())

    @override_settings(
        ML_API_ACCESS_TOKEN='',
        ML_API_CLIENT_ID='',
        ML_API_CLIENT_SECRET='',
        ML_API_REFRESH_TOKEN='',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_missing_api_configuration_is_reported_without_request(self):
        client = Mock()
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ) as client_cls:
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        client_cls.assert_not_called()
        client.get.assert_not_called()
        self.assertIn('ML_API_ACCESS_TOKEN', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_malformed_probe_results_is_rejected(self):
        client = Mock()
        client.get.return_value = {
            'paging': {'total': 1, 'offset': 0, 'limit': 1},
            'results': 'not-a-list',
        }
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertIn('results inválido', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_malformed_probe_paging_is_rejected(self):
        client = Mock()
        client.get.return_value = {'paging': [], 'results': []}
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertIn('paging inválido', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_malformed_probe_total_is_rejected(self):
        client = Mock()
        client.get.return_value = {
            'paging': {'total': '1', 'offset': 0, 'limit': 1},
            'results': [],
        }
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertIn('paging.total inválido', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_authentication_error_is_converted_to_command_error(self):
        client = Mock()
        client.get.side_effect = MercadoLivreApiError(
            'Token rejeitado.',
            status_code=401,
            endpoint='/sites/MLB/search',
            auth_error=True,
        )
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertIn('HTTP 401', str(context.exception))
        self.assertNotIn('Token rejeitado', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_malformed_http_status_is_reported_as_network_failure(self):
        for status_code in (True, '401', 401.5):
            with self.subTest(status_code=status_code):
                client = Mock()
                client.get.side_effect = MercadoLivreApiError(
                    'internal',
                    status_code=cast(int, status_code),
                    endpoint='/sites/MLB/search',
                )
                with patch(
                    'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
                    return_value=client,
                ):
                    with self.assertRaises(CommandError) as context:
                        call_command('check_mercadolivre_api', '--limit', '1')
                self.assertIn('HTTP rede', str(context.exception))
                self.assertNotIn(f'HTTP {status_code}', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_probe_rejects_missing_or_invalid_total(self):
        for paging in ({}, {'total': None, 'offset': 0, 'limit': 1},
                       {'total': -1, 'offset': 0, 'limit': 1},
                       {'total': True, 'offset': 0, 'limit': 1}):
            with self.subTest(paging=paging):
                client = Mock()
                client.get.return_value = {'paging': paging, 'results': []}
                with patch(
                    'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
                    return_value=client,
                ):
                    with self.assertRaises(CommandError):
                        call_command('check_mercadolivre_api', '--limit', '1')

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_probe_rejects_non_string_result_item(self):
        client = Mock()
        client.get.return_value = {
            'paging': {'total': 1, 'offset': 0, 'limit': 1},
            'results': [1],
        }
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
            return_value=client,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertIn('item de results inválido', str(context.exception))

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_probe_rejects_semantically_inconsistent_page(self):
        payloads = (
            {
                'paging': {'total': 0, 'offset': 0, 'limit': 1},
                'results': ['MLB1'],
            },
            {
                'paging': {'total': 1, 'offset': 0, 'limit': 1},
                'results': [],
            },
            {
                'paging': {'total': 1, 'offset': 1, 'limit': 1},
                'results': ['MLB1'],
            },
            {
                'paging': {'total': 1, 'offset': 0, 'limit': 2},
                'results': ['MLB1'],
            },
            {
                'paging': {'total': 1, 'offset': 0, 'limit': 1},
                'results': ['BAD1'],
            },
            {
                'paging': {'total': 2, 'offset': 0, 'limit': 1},
                'results': ['MLB1', 'MLB2'],
            },
            {
                'paging': {'total': 1, 'offset': 0, 'limit': 1},
                'results': ['MLBABC'],
            },
            {
                'paging': {'total': 2, 'offset': 0, 'limit': 2},
                'results': ['MLB1'],
            },
            {
                'paging': {'total': 2, 'offset': 0, 'limit': 2},
                'results': ['MLB1', 'MLB1'],
            },
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                client = Mock()
                client.get.return_value = payload
                with patch(
                    'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
                    return_value=client,
                ):
                    with self.assertRaises(CommandError):
                        call_command('check_mercadolivre_api', '--limit', '1')

    def test_configuration_exception_metadata_is_not_exposed(self):
        error = MercadoLivreAuthError(
            'secret-sentinel',
            code='configuration_incomplete',
            missing_fields=('ML_API_ACCESS_TOKEN', 'secret-sentinel'),
        )
        with patch(
            'apps.marketplaces.management.commands.check_mercadolivre_api.validate_api_configuration',
            side_effect=error,
        ):
            with self.assertRaises(CommandError) as context:
                call_command('check_mercadolivre_api', '--limit', '1')
        self.assertNotIn('secret-sentinel', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_unexpected_and_auth_exceptions_are_sanitized(self):
        for error in (
            RuntimeError('secret-sentinel'),
            MercadoLivreAuthError('secret-sentinel'),
        ):
            with self.subTest(error=type(error).__name__):
                client = Mock()
                client.get.side_effect = error
                with patch(
                    'apps.marketplaces.management.commands.check_mercadolivre_api.MercadoLivreApiClient',
                    return_value=client,
                ):
                    with self.assertRaises(CommandError) as context:
                        call_command('check_mercadolivre_api', '--limit', '1')
                self.assertNotIn('secret-sentinel', str(context.exception))
