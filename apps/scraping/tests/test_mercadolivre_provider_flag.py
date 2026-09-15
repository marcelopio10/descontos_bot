import os
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.panel.models import Setting
from apps.marketplaces.models import Marketplace
from apps.scraping.services import adapters


class MercadoLivreProviderFlagTests(TestCase):
    def test_enabled_api_provider_is_used_by_runner(self):
        marketplace = Marketplace.objects.create(code='mercadolivre', name='Mercado Livre')
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with patch(
                'apps.scraping.services.mercadolivre_api_adapter.MercadoLivreApiAdapter.run',
                return_value=SimpleNamespace(
                    errors=[],
                    total_collected=2,
                    total_valid=1,
                    total_created=1,
                    total_updated=0,
                    total_discarded=1,
                ),
            ):
                from apps.scraping.services.runner import run_marketplace_scraping

                result = run_marketplace_scraping(marketplace, max_pages=1)
        result.run.refresh_from_db()
        self.assertEqual(result.run.provider, 'mercadolivre_api')
        self.assertEqual(result.total_valid, 1)

    def test_zero_valid_api_run_is_failed_and_auditable(self):
        marketplace = Marketplace.objects.create(code='mercadolivre', name='Mercado Livre')
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with patch(
                'apps.scraping.services.mercadolivre_api_adapter.MercadoLivreApiAdapter.run',
                return_value=SimpleNamespace(
                    errors=[],
                    total_collected=1,
                    total_valid=0,
                    total_created=0,
                    total_updated=0,
                    total_discarded=1,
                ),
            ), patch('apps.scraping.services.runner.alertar_scraper_zero_ofertas'):
                from apps.scraping.services.runner import run_marketplace_scraping

                result = run_marketplace_scraping(marketplace, max_pages=1)
        result.run.refresh_from_db()
        self.assertEqual(result.run.status, 'failed')
        self.assertIn('Nenhuma oferta válida', result.run.error_message)

    def test_api_provider_requires_explicit_enablement(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch('apps.scraping.services.adapters.MercadoLivreApiAdapter') as api_cls, patch(
                'apps.scraping.services.adapters.mercado_livre.build_from_env',
            ) as legacy_factory:
                result = adapters.build_adapter('mercadolivre')

        api_cls.assert_not_called()
        legacy_factory.assert_called_once_with()
        self.assertIs(result.scraper, legacy_factory.return_value)

    def test_zero_flag_selects_legacy_scraper(self):
        Setting.objects.create(
            key='mercadolivre_api_search_enabled',
            value='0',
            description='rollback',
        )
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with patch('apps.scraping.services.adapters.MercadoLivreApiAdapter') as api_cls, patch(
                'apps.scraping.services.adapters.mercado_livre.build_from_env',
            ) as legacy_factory:
                adapters.build_adapter('mercadolivre')
        api_cls.assert_not_called()
        legacy_factory.assert_called_once_with()

    def test_invalid_environment_flag_fails_closed(self):
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'maybe'}):
            with self.assertRaises(ValueError):
                adapters.build_adapter('mercadolivre')

    def test_flag_storage_failure_is_sanitized(self):
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with patch(
                'apps.scraping.services.adapters.Setting.objects.filter',
                side_effect=RuntimeError('FLAG_DB_SECRET'),
            ):
                with self.assertRaises(ValueError) as context:
                    adapters.build_adapter('mercadolivre')

        self.assertNotIn('FLAG_DB_SECRET', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    def test_non_binary_persisted_flag_fails_closed(self):
        for value in ('', 'maybe', '2', '-1'):
            with self.subTest(value=value):
                Setting.objects.update_or_create(
                    key='mercadolivre_api_search_enabled',
                    defaults={'value': value},
                )
                with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
                    with patch('apps.scraping.services.adapters.MercadoLivreApiAdapter') as api_cls, patch(
                        'apps.scraping.services.adapters.mercado_livre.build_from_env',
                    ) as legacy_factory:
                        result = adapters.build_adapter('mercadolivre')
                api_cls.assert_not_called()
                legacy_factory.assert_called_once_with()
                self.assertIs(result.scraper, legacy_factory.return_value)

    @override_settings(
        ML_API_ACCESS_TOKEN='',
        ML_API_CLIENT_ID='',
        ML_API_CLIENT_SECRET='',
        ML_API_REFRESH_TOKEN='',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_api_adapter_validates_before_building_pipeline(self):
        from apps.marketplaces.services.mercadolivre_auth import MercadoLivreAuthError
        from apps.scraping.services.mercadolivre_api_adapter import MercadoLivreApiAdapter

        pipeline_factory = Mock()
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with self.assertRaises(MercadoLivreAuthError):
                MercadoLivreApiAdapter(pipeline_factory=pipeline_factory).run(
                    marketplace=None,
                    run=None,
                    max_pages=1,
                )
        pipeline_factory.assert_not_called()

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_api_adapter_rechecks_disabled_flag_before_pipeline(self):
        from apps.marketplaces.services.mercadolivre_auth import MercadoLivreAuthError
        from apps.scraping.services.mercadolivre_api_adapter import MercadoLivreApiAdapter

        pipeline_factory = Mock()
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'false'}):
            with self.assertRaises(MercadoLivreAuthError):
                MercadoLivreApiAdapter(pipeline_factory=pipeline_factory).run(
                    marketplace=None,
                    run=None,
                    max_pages=1,
                )
        pipeline_factory.assert_not_called()

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_api_adapter_sanitizes_invalid_flag_error(self):
        from apps.marketplaces.services.mercadolivre_auth import MercadoLivreAuthError
        from apps.scraping.services.mercadolivre_api_adapter import MercadoLivreApiAdapter

        pipeline_factory = Mock()
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'secret-sentinel'}):
            with self.assertRaises(MercadoLivreAuthError) as context:
                MercadoLivreApiAdapter(pipeline_factory=pipeline_factory).run(
                    marketplace=None,
                    run=None,
                    max_pages=1,
                )
        self.assertNotIn('secret-sentinel', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)
        pipeline_factory.assert_not_called()

    @override_settings(
        ML_API_ACCESS_TOKEN='access',
        ML_API_CLIENT_ID='client',
        ML_API_CLIENT_SECRET='secret',
        ML_API_REFRESH_TOKEN='refresh',
        ML_API_SITE_ID='MLB',
        ML_API_BASE_URL='https://api.mercadolibre.com',
    )
    def test_api_adapter_sanitizes_pipeline_failure(self):
        from apps.marketplaces.services.mercadolivre_auth import MercadoLivreAuthError
        from apps.scraping.services.mercadolivre_api_adapter import MercadoLivreApiAdapter

        pipeline_factory = Mock(side_effect=RuntimeError('secret-sentinel'))
        with patch.dict(os.environ, {'MERCADOLIVRE_API_SEARCH_ENABLED': 'true'}):
            with self.assertRaises(MercadoLivreAuthError) as context:
                MercadoLivreApiAdapter(pipeline_factory=pipeline_factory).run(
                    marketplace=None,
                    run=None,
                    max_pages=1,
                )
        self.assertNotIn('secret-sentinel', str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)
        pipeline_factory.assert_called_once()

    def test_seed_settings_preserves_explicit_rollback(self):
        setting = Setting.objects.create(
            key='mercadolivre_api_search_enabled',
            value='0',
            description='rollback',
        )
        call_command('seed_settings', stdout=StringIO())
        setting.refresh_from_db()
        self.assertEqual(setting.value, '0')
