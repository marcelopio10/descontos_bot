from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.market_intel.models import (
    LearningEvent,
    MarketIntelCursor,
    MarketLearningSnapshot,
    ObservedOpportunity,
    ObservedWhatsAppGroup,
    ObservedWhatsAppMessage,
)
from apps.market_intel.services.incremental import (
    build_learning_snapshot,
    ingest_incremental_messages,
)


class IncrementalIntelligenceTests(TestCase):
    def _message(self, message_id, text, sent_at=None, urls=None):
        group, _ = ObservedWhatsAppGroup.objects.get_or_create(
            jid='120363000000000001@g.us',
            defaults={'name': 'Grupo Ofertas'},
        )
        return ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id=message_id,
            sender_hash='a' * 64,
            sent_at=sent_at or timezone.now() - timedelta(minutes=5),
            collected_at=timezone.now(),
            text=text,
            urls=urls or [],
            parsed_marketplace='mercadolivre',
            parsed_price=Decimal('47.84'),
            parsed_discount_pct=Decimal('65.00'),
            parsed_coupon='OFICIALMODA',
            scraper_hints=['categoria:moda', 'faixa_preco:ate_100'],
            marca='nike',
        )

    def test_incremental_ingestion_is_idempotent_and_creates_aggregated_opportunity(self):
        message = self._message(
            'msg-1',
            'Oferta Nike por R$ 47,84',
            urls=['https://meli.la/abc'],
        )

        first = ingest_incremental_messages()
        second = ingest_incremental_messages()

        self.assertEqual(first['processed'], 1)
        self.assertEqual(second['processed'], 0)
        opportunity = ObservedOpportunity.objects.get()
        self.assertEqual(opportunity.occurrence_count, 1)
        self.assertEqual(opportunity.marketplace, 'mercadolivre')
        self.assertEqual(opportunity.status, ObservedOpportunity.Status.OBSERVED)
        self.assertEqual(opportunity.last_message_id, message.id)
        self.assertEqual(MarketIntelCursor.objects.get(source='whatsapp').processed_count, 1)

    def test_repeated_fingerprint_updates_occurrence_without_duplicate(self):
        self._message('msg-1', 'Nike por R$ 47,84', urls=['https://meli.la/abc'])
        self._message('msg-2', 'Nike novamente por R$ 45,00', urls=['https://meli.la/abc'])

        result = ingest_incremental_messages()

        self.assertEqual(result['processed'], 2)
        self.assertEqual(ObservedOpportunity.objects.count(), 1)
        self.assertEqual(ObservedOpportunity.objects.get().occurrence_count, 2)

    def test_learning_snapshot_contains_sanitized_recommendations(self):
        self._message('msg-1', 'Nike por R$ 47,84', urls=['https://meli.la/abc'])
        ingest_incremental_messages()

        snapshot = build_learning_snapshot()

        self.assertIsInstance(snapshot, MarketLearningSnapshot)
        self.assertEqual(snapshot.state, MarketLearningSnapshot.State.SHADOW)
        self.assertEqual(snapshot.payload['funnel']['observed_messages'], 1)
        self.assertEqual(snapshot.payload['recommendations'][0]['key'], 'moda')
        self.assertNotIn('https://', str(snapshot.payload))
        self.assertTrue(all('https://' not in str(event.payload) for event in LearningEvent.objects.all()))
