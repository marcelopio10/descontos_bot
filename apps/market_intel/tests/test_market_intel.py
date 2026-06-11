from datetime import date, timedelta
from decimal import Decimal

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
            name='Ofertas A',
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
        serialized = str(payload)

        self.assertEqual(report.messages_analyzed, 1)
        self.assertEqual(payload['summary']['top_marketplaces'][0]['marketplace'], 'amazon')
        self.assertNotIn('sender_hash', serialized)
        self.assertNotIn('https://amzn.to/oferta', serialized)
        self.assertIn('termo:air fryer', serialized)
