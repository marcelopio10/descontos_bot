from django.test import SimpleTestCase, override_settings

from apps.distribution.services.whatsapp_client import WhatsAppClient


class WhatsAppClientProviderSettingsTests(SimpleTestCase):
    @override_settings(
        WA_PROVIDER='baileys',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_defaults_to_baileys_service_url(self):
        client = WhatsAppClient()

        self.assertEqual(client.base_url, 'http://127.0.0.1:8787')

    @override_settings(
        WA_PROVIDER='evolution',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_evolution_provider_uses_adapter_url(self):
        client = WhatsAppClient()

        self.assertEqual(client.base_url, 'http://127.0.0.1:8788')

    @override_settings(
        WA_PROVIDER='evolution',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_explicit_base_url_overrides_provider(self):
        client = WhatsAppClient(base_url='http://127.0.0.1:9999/')

        self.assertEqual(client.base_url, 'http://127.0.0.1:9999')
