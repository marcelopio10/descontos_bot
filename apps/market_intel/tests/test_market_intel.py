from datetime import date, timedelta
from decimal import Decimal
import json

from django.test import TestCase
from django.utils import timezone

from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.market_intel.services.parser import parse_observed_message
from apps.market_intel.services.reports import build_daily_report_payload, generate_daily_report


class MarketIntelParserTests(TestCase):
    def test_parser_extracts_marketplace_price_coupon_and_labels(self):
        parsed = parse_observed_message(
            'Corre! Air Fryer por R$ 199,90 com cupom CASA10 https://amzn.to/oferta'
        )

        self.assertEqual(parsed['marketplace'], 'amazon')
        self.assertEqual(parsed['price'], '199.90')
        self.assertEqual(parsed['coupon'], 'CASA10')
        self.assertIn('urgencia', parsed['labels'])
        self.assertIn('cupom', parsed['labels'])
        self.assertIn('ate_300', parsed['labels'])
        self.assertIn('termo:air fryer', parsed['scraper_hints'])

    def test_parser_calculates_discount_when_original_price_exists(self):
        parsed = parse_observed_message('De R$ 299,90 por R$ 199,90 https://mercadolivre.com.br/oferta')

        self.assertEqual(parsed['marketplace'], 'mercadolivre')
        self.assertEqual(parsed['price'], '199.90')
        self.assertEqual(parsed['original_price'], '299.90')
        self.assertEqual(parsed['discount_pct'], '33.34')

    def test_parser_extracts_coupon_after_label_punctuation_or_connector(self):
        examples = {
            'Cupom: TESTE10': 'TESTE10',
            'cupom - TESTE10': 'TESTE10',
            'use o cupom TESTE10': 'TESTE10',
            'aplique o cupom TESTE10': 'TESTE10',
        }

        for text, expected_coupon in examples.items():
            with self.subTest(text=text):
                parsed = parse_observed_message(text)
                self.assertEqual(parsed['coupon'], expected_coupon)
                self.assertIn('cupom', parsed['labels'])


class MarketIntelReportTests(TestCase):
    def test_generate_daily_report_aggregates_without_exposing_sender_or_raw_urls(self):
        group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas A https://grupo.example 120363000000000001@g.us 5521983554018-1540851269@g.us 5511999999999:12@s.whatsapp.net',
            jid='120363000000000001@g.us',
            is_enabled=True,
        )
        sent_at = timezone.now() - timedelta(hours=1)
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='MSG1',
            sender_hash='a' * 64,
            sent_at=sent_at,
            collected_at=sent_at,
            text='Corre! Air Fryer por R$ 199,90 com cupom CASA10 https://amzn.to/oferta',
            urls=['https://amzn.to/oferta'],
            has_image=True,
            raw_type='imageMessage',
            parsed_marketplace='amazon',
            parsed_price=Decimal('199.90'),
            parsed_coupon='CASA10',
            editorial_labels=['urgencia', 'cupom', 'ate_300', 'imagem'],
            scraper_hints=['termo:air fryer', 'categoria:casa/cozinha'],
        )

        report = generate_daily_report(date.today())
        payload = build_daily_report_payload(report)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(report.messages_analyzed, 1)
        self.assertEqual(payload['cycle_summary']['top_marketplaces'][0]['marketplace'], 'amazon')
        self.assertEqual(payload['summary']['messages_analyzed'], 1)
        self.assertEqual(payload['analyzed_offers'][0]['marketplace'], 'amazon')
        self.assertNotIn('"sender_hash"', serialized)
        self.assertNotIn('"message_id"', serialized)
        self.assertNotIn('120363000000000001@g.us', serialized)
        self.assertNotIn('5521983554018-1540851269@g.us', serialized)
        self.assertNotIn('5511999999999:12@s.whatsapp.net', serialized)
        self.assertNotIn('https://amzn.to/oferta', serialized)
        self.assertIn('termo:air fryer', serialized)

    def test_payload_is_incremental_and_includes_previous_analyzed_offers_without_private_fields(self):
        group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas A https://grupo.example 120363000000000001@g.us 5521983554018-1540851269@g.us 5511999999999:12@s.whatsapp.net',
            jid='120363000000000001@g.us',
            is_enabled=True,
        )
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='OLD1',
            sender_hash='b' * 64,
            sent_at=yesterday,
            collected_at=yesterday,
            text='Oferta antiga com link https://amzn.to/antiga',
            urls=['https://amzn.to/antiga'],
            has_image=False,
            raw_type='conversation',
            parsed_marketplace='amazon',
            parsed_price=Decimal('99.90'),
            parsed_coupon='',
            editorial_labels=['ate_100', 'https://amzn.to/label', 'texto copiado da oferta'],
            scraper_hints=['faixa_preco:ate_100', 'https://amzn.to/hint', 'termo:Air Fryer por R$ 199'],
        )
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='NEW1',
            sender_hash='c' * 64,
            sent_at=now,
            collected_at=now,
            text='Oferta nova com link https://mercadolivre.com.br/nova',
            urls=['https://mercadolivre.com.br/nova'],
            has_image=True,
            raw_type='imageMessage',
            parsed_marketplace='mercadolivre',
            parsed_price=Decimal('149.90'),
            parsed_coupon='NOVO10',
            editorial_labels=['cupom', 'imagem', 'ate_300'],
            scraper_hints=['faixa_preco:ate_300'],
        )

        report = generate_daily_report(date.today())
        report.summary_json = {'top_groups': [{'group': '120363000000000001@g.us https://leak.example', 'count': 99}]}
        report.recommendations_json = [{'title': 'Oferta antiga https://leak.example'}]
        report.scraper_opportunities_json = [{'hint': 'https://leak.example', 'count': 99}]
        report.save(update_fields=['summary_json', 'recommendations_json', 'scraper_opportunities_json', 'updated_at'])
        payload = build_daily_report_payload(report)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(report.messages_analyzed, 1)
        self.assertEqual(payload['cycle_summary']['messages_analyzed'], 1)
        self.assertEqual(payload['summary']['messages_analyzed'], 2)
        self.assertEqual(len(payload['analyzed_offers']), 2)
        self.assertEqual(
            [offer['marketplace'] for offer in payload['analyzed_offers']],
            ['mercadolivre', 'amazon'],
        )
        self.assertNotIn('"sender_hash"', serialized)
        self.assertNotIn('"message_id"', serialized)
        self.assertNotIn('OLD1', serialized)
        self.assertNotIn('NEW1', serialized)
        self.assertNotIn('120363000000000001@g.us', serialized)
        self.assertNotIn('5521983554018-1540851269@g.us', serialized)
        self.assertNotIn('5511999999999:12@s.whatsapp.net', serialized)
        self.assertNotIn('https://amzn.to/antiga', serialized)
        self.assertNotIn('https://mercadolivre.com.br/nova', serialized)
        self.assertNotIn('https://amzn.to/label', serialized)
        self.assertNotIn('https://amzn.to/hint', serialized)
        self.assertNotIn('texto copiado da oferta', serialized)
        self.assertNotIn('Air Fryer por R$ 199', serialized)
        self.assertNotIn('grupo.example', serialized)
        self.assertNotIn('leak.example', serialized)
        self.assertNotIn('Oferta antiga', serialized)
        self.assertNotIn('Oferta nova', serialized)
