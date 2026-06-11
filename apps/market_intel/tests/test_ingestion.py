import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.market_intel.services.whatsapp_observer_client import WhatsAppObserverClient
from apps.market_intel.services.ingestion import import_observed_messages


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode('utf-8')


class WhatsAppObserverClientTests(TestCase):
    def test_collect_calls_local_observer_endpoint(self):
        payload = {'enabled': True, 'messages': []}
        with patch('apps.market_intel.services.whatsapp_observer_client.urlopen', return_value=DummyResponse(payload)) as mocked:
            result = WhatsAppObserverClient(base_url='http://127.0.0.1:8787').collect()

        self.assertEqual(result, payload)
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8787/observer/collect')
        self.assertEqual(request.method, 'POST')


class ImportObservedMessagesTests(TestCase):
    def test_import_creates_group_message_and_parsed_fields(self):
        payload = {
            'enabled': True,
            'messages': [
                {
                    'message_id': 'MSG1',
                    'group_jid': '120363000000000001@g.us',
                    'group_subject': 'Ofertas A',
                    'sender_hash': 'a' * 64,
                    'sent_at': '2026-06-11T23:20:00.000Z',
                    'collected_at': '2026-06-11T23:30:00.000Z',
                    'text': 'Corre! Air Fryer por R$ 199,90 com cupom CASA10 https://amzn.to/oferta',
                    'has_image': True,
                    'urls': ['https://amzn.to/oferta'],
                    'raw_type': 'imageMessage',
                }
            ],
        }

        result = import_observed_messages(payload)

        self.assertEqual(result['created'], 1)
        group = ObservedWhatsAppGroup.objects.get(jid='120363000000000001@g.us')
        message = ObservedWhatsAppMessage.objects.get(group=group, external_message_id='MSG1')
        self.assertEqual(message.parsed_marketplace, 'amazon')
        self.assertEqual(message.parsed_price, Decimal('199.90'))
        self.assertEqual(message.parsed_coupon, 'CASA10')
        self.assertIn('imagem', message.editorial_labels)
