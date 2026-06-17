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

    def test_import_persists_v2_fields(self):
        payload = {
            'enabled': True,
            'messages': [
                {
                    'message_id': 'MSG2',
                    'group_jid': '120363000000000001@g.us',
                    'group_subject': 'Ofertas V2',
                    'sender_hash': 'b' * 64,
                    'sent_at': '2026-06-11T23:20:00.000Z',
                    'collected_at': '2026-06-11T23:30:00.000Z',
                    'text': '🔥 Com 10% off no Pix! Nike Air Max 12x s/ juros R$ 599,90 menor preço! https://mercadolivre.com.br/x',
                    'has_image': True,
                    'urls': ['https://mercadolivre.com.br/x'],
                    'raw_type': 'imageMessage',
                }
            ],
        }

        result = import_observed_messages(payload)
        self.assertEqual(result['created'], 1)

        message = ObservedWhatsAppMessage.objects.get(external_message_id='MSG2')
        # v1 fields still work
        self.assertEqual(message.parsed_marketplace, 'mercadolivre')
        self.assertIn('pix', message.editorial_labels)
        self.assertIn('parcelado_sem_juros', message.editorial_labels)
        self.assertIn('menor_preco', message.editorial_labels)
        # v2 fields
        self.assertEqual(message.parcelamento, 12)
        self.assertTrue(message.parcelado_sem_juros)
        self.assertTrue(message.pix)
        self.assertTrue(message.menor_preco)
        self.assertEqual(message.marca, 'nike')
        # Text has "10% off" but not a coupon code — cupom_tipo should be empty
        self.assertEqual(message.cupom_tipo, '')
        self.assertIsNotNone(message.emoji_densidade)

    def test_import_with_engagement_fields(self):
        """P0-1: Engagement fields can be passed through ingestion."""
        payload = {
            'enabled': True,
            'messages': [
                {
                    'message_id': 'MSG3',
                    'group_jid': '120363000000000001@g.us',
                    'group_subject': 'Telegram Ofertas',
                    'sender_hash': 'c' * 64,
                    'sent_at': '2026-06-11T23:20:00.000Z',
                    'collected_at': '2026-06-11T23:30:00.000Z',
                    'text': 'Oferta com engajamento https://shopee.com.br/x',
                    'has_image': False,
                    'urls': ['https://shopee.com.br/x'],
                    'raw_type': 'conversation',
                    'reacoes': 412,
                    'visualizacoes': 18000,
                    'fixado': True,
                }
            ],
        }

        result = import_observed_messages(payload)
        self.assertEqual(result['created'], 1)

        message = ObservedWhatsAppMessage.objects.get(external_message_id='MSG3')
        self.assertEqual(message.reacoes, 412)
        self.assertEqual(message.visualizacoes, 18000)
        self.assertTrue(message.fixado)

    def test_import_null_engagement_fields_are_preserved(self):
        """When engagement fields are absent, they stay null (degradation)."""
        payload = {
            'enabled': True,
            'messages': [
                {
                    'message_id': 'MSG4',
                    'group_jid': '120363000000000001@g.us',
                    'group_subject': 'WA Ofertas',
                    'sender_hash': 'd' * 64,
                    'sent_at': '2026-06-11T23:20:00.000Z',
                    'collected_at': '2026-06-11T23:30:00.000Z',
                    'text': 'Oferta WA sem engajamento',
                    'has_image': False,
                    'urls': [],
                    'raw_type': 'conversation',
                }
            ],
        }

        result = import_observed_messages(payload)
        self.assertEqual(result['created'], 1)

        message = ObservedWhatsAppMessage.objects.get(external_message_id='MSG4')
        self.assertIsNone(message.reacoes)
        self.assertIsNone(message.visualizacoes)
        self.assertIsNone(message.fixado)