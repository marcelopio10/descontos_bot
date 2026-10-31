from unittest.mock import Mock

from django.test import SimpleTestCase

from apps.marketplaces.services.mercadolivre_affiliate_adapter import (
    ExistingAffiliateLinkEngineAdapter,
)


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


class MercadoLivreAffiliateAdapterTests(SimpleTestCase):
    def test_success_returns_generated_short_url(self):
        for short_url in (
            'https://mercadolivre.com/sec/abc', 'https://meli.la/Abc1234',
        ):
            with self.subTest(short_url=short_url):
                session = Mock()
                session.post.return_value = Response(200, {'short_url': short_url})
                adapter = ExistingAffiliateLinkEngineAdapter(
                    affiliate_tag='tag',
                    ml_cookie='cookie',
                    ml_csrf='csrf',
                    session_factory=lambda: session,
                )

                result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

                self.assertTrue(result.generated)
                self.assertEqual(result.url, short_url)
                self.assertEqual(session.post.call_args.kwargs['json']['url'], 'https://produto.mercadolivre.com.br/MLB-1')
                self.assertFalse(session.post.call_args.kwargs['allow_redirects'])

    def test_missing_credentials_returns_original_and_alerts_once(self):
        alert = Mock()
        adapter = ExistingAffiliateLinkEngineAdapter(alert_callback=alert)
        original = 'https://produto.mercadolivre.com.br/MLB-1'

        self.assertEqual(adapter.generate(original), original)
        self.assertEqual(adapter.generate(original), original)
        alert.assert_called_once()

    def test_401_returns_original_without_leaking_cookie(self):
        session = Mock()
        session.post.return_value = Response(401)
        alert = Mock()
        adapter = ExistingAffiliateLinkEngineAdapter(
            affiliate_tag='tag',
            ml_cookie='very-secret-cookie',
            ml_csrf='very-secret-csrf',
            session_factory=lambda: session,
            alert_callback=alert,
        )

        result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

        self.assertFalse(result.generated)
        self.assertNotIn('very-secret-cookie', str(alert.call_args))
        self.assertNotIn('very-secret-csrf', str(alert.call_args))

    def test_unsafe_generated_url_returns_original(self):
        for short_url in (
            'javascript:alert(1)',
            'https://evil.example/sec/abc',
            'https://user:pass@mercadolivre.com/sec/abc',
            'http://mercadolivre.com/sec/abc',
            'https://mercadolivre.com/sec/a\nb',
            'https://mercadolivre.com/sec/a\x00b',
            'https://mercadolivre.com/',
            'https://mercadolivre.com/?next=https://evil.example',
            'https://mercadolivre.com/sec/abc?',
            'https://mercadolivre.com/sec/a%2Fb',
            'https://mercadolivre.com/sec/%2e%2e%2fevil',
            '\nhttps://mercadolivre.com/sec/abc',
            'https://mercadolivre.com/sec/abc\t',
            'https://meli.la/',
            'https://meli.la/..',
            'https://meli.la/abc/extra',
            'https://meli.la/abc?next=https://evil.example',
            'https://meli.la/abc#fragment',
            'https://evil.meli.la/abc',
            'https://user:pass@meli.la/abc',
            'https://meli.la:443/abc',
        ):
            with self.subTest(short_url=short_url):
                session = Mock()
                session.post.return_value = Response(200, {'short_url': short_url})
                adapter = ExistingAffiliateLinkEngineAdapter(
                    affiliate_tag='tag',
                    ml_cookie='cookie',
                    ml_csrf='csrf',
                    session_factory=lambda: session,
                )

                result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

                self.assertFalse(result.generated)
                self.assertEqual(result.url, 'https://produto.mercadolivre.com.br/MLB-1')

    def test_external_original_url_never_reaches_affiliate_endpoint(self):
        for original_url in (
            'https://evil.example/product',
            'data:text/plain,secret',
            'https://produto.mercadolivre.com.br/foo/MLB-1/bar',
            'https://produto.mercadolivre.com.br/MLB-1%2Fextra',
            'https://produto.mercadolivre.com.br/MLB-1/../MLB-2',
            'https://produto.mercadolivre.com.br/MLB-1-foo-MLB2',
            'https://produto.mercadolivre.com.br/MLB-1-%2e%2e',
            'https://produto.mercadolivre.com.br/MLB-1-%3fquery',
            '\nhttps://produto.mercadolivre.com.br/MLB-1',
            'https://produto.mercadolivre.com.br/MLB-1\t',
        ):
            with self.subTest(original_url=original_url):
                session = Mock()
                adapter = ExistingAffiliateLinkEngineAdapter(
                    affiliate_tag='tag',
                    ml_cookie='cookie',
                    ml_csrf='csrf',
                    session_factory=lambda: session,
                )

                result = adapter.generate_result(original_url)

                self.assertFalse(result.generated)
                self.assertEqual(result.url, '')
                session.post.assert_not_called()

    def test_whitespace_credentials_are_missing(self):
        session = Mock()
        alert = Mock()
        adapter = ExistingAffiliateLinkEngineAdapter(
            affiliate_tag='  ',
            ml_cookie='\t',
            ml_csrf='\n',
            session_factory=lambda: session,
            alert_callback=alert,
        )

        result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

        self.assertFalse(result.generated)
        self.assertEqual(result.error_code, 'credentials_missing')
        session.post.assert_not_called()
        alert.assert_called_once()

    def test_malformed_http_status_is_rejected(self):
        session = Mock()
        session.post.return_value = Mock(status_code='200')
        adapter = ExistingAffiliateLinkEngineAdapter(
            affiliate_tag='tag',
            ml_cookie='cookie',
            ml_csrf='csrf',
            session_factory=lambda: session,
        )

        result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

        self.assertFalse(result.generated)
        self.assertEqual(result.error_code, 'affiliate_response_invalid')

    def test_status_subclass_and_out_of_range_are_rejected_without_leaking(self):
        class SneakyInt(int):
            def __str__(self):
                return 'STATUS_SECRET_SENTINEL'

        for status_code in (SneakyInt(401), 600):
            with self.subTest(status_code=type(status_code).__name__):
                session = Mock()
                session.post.return_value = Response(status_code)
                adapter = ExistingAffiliateLinkEngineAdapter(
                    affiliate_tag='tag',
                    ml_cookie='cookie',
                    ml_csrf='csrf',
                    session_factory=lambda: session,
                )

                result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

                self.assertFalse(result.generated)
                self.assertEqual(result.error_code, 'affiliate_response_invalid')

    def test_alert_callback_failure_does_not_break_fallback(self):
        alert = Mock(side_effect=RuntimeError('alert-sentinel'))
        adapter = ExistingAffiliateLinkEngineAdapter(alert_callback=alert)

        result = adapter.generate_result('https://produto.mercadolivre.com.br/MLB-1')

        self.assertFalse(result.generated)
        self.assertEqual(result.error_code, 'credentials_missing')
