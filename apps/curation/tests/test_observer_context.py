from django.test import TestCase
from django.utils import timezone

from apps.curation.services.observer_context import assert_sanitized_context, build_observer_context
from apps.market_intel.models import MarketIntelDailyReport, ObservedWhatsAppGroup, ObservedWhatsAppMessage


class ObserverContextTests(TestCase):
    def test_context_aggregates_messages_without_sensitive_fields(self):
        group = ObservedWhatsAppGroup.objects.create(name='Grupo Ofertas', jid='123@g.us')
        now = timezone.now()
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='msg-1',
            sender_hash='secret-sender',
            sent_at=now,
            collected_at=now,
            text='Texto bruto com https://example.com/oferta',
            urls=['https://example.com/oferta'],
            has_image=True,
            parsed_marketplace='amazon',
            editorial_labels=['pix', 'cupom'],
        )
        MarketIntelDailyReport.objects.create(
            date=now.date(),
            window_start=now,
            window_end=now,
            groups_analyzed=1,
            messages_analyzed=1,
            summary_json={
                'ok': True,
                'group_jid': '123@g.us',
                'nested': {'url': 'https://example.com/raw', 'safe': 'valor'},
            },
        )

        context = build_observer_context(lookback_hours=1)

        self.assertEqual(context['messages_analyzed'], 1)
        self.assertEqual(context['marketplace_counts'], {'amazon': 1})
        self.assertEqual(context['editorial_label_counts'], {'pix': 1, 'cupom': 1})
        serialized = str(context)
        self.assertNotIn('123@g.us', serialized)
        self.assertNotIn('secret-sender', serialized)
        self.assertNotIn('https://example.com', serialized)
        self.assertNotIn('Texto bruto', serialized)

    def test_assert_sanitized_context_rejects_sensitive_keys_and_values(self):
        with self.assertRaises(ValueError):
            assert_sanitized_context({'sender_hash': 'abc'})
        with self.assertRaises(ValueError):
            assert_sanitized_context({'nested': {'value': 'https://example.com'}})
