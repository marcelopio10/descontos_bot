from django.test import SimpleTestCase, override_settings

from apps.market_intel.services.whatsapp_observer_client import WhatsAppObserverClient


class WhatsAppObserverClientProviderSettingsTests(SimpleTestCase):
    @override_settings(
        WA_PROVIDER='baileys',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_defaults_to_baileys_service_url(self):
        client = WhatsAppObserverClient()

        self.assertEqual(client.base_url, 'http://127.0.0.1:8787')
        self.assertEqual(client.service_label, 'wa_service')

    @override_settings(
        WA_PROVIDER='evolution',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_evolution_provider_uses_adapter_url(self):
        client = WhatsAppObserverClient()

        self.assertEqual(client.base_url, 'http://127.0.0.1:8788')
        self.assertEqual(client.service_label, 'Evolution adapter')

    @override_settings(
        WA_PROVIDER='evolution',
        WA_SERVICE_URL='http://127.0.0.1:8787',
        EVOLUTION_ADAPTER_URL='http://127.0.0.1:8788',
    )
    def test_explicit_base_url_overrides_provider(self):
        client = WhatsAppObserverClient(base_url='http://127.0.0.1:9999/')

        self.assertEqual(client.base_url, 'http://127.0.0.1:9999')
        self.assertEqual(client.service_label, 'Evolution adapter')
