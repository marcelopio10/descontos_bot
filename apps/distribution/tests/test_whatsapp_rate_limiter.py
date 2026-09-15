from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.distribution.models import WhatsAppThrottleState


class WhatsAppThrottleStateTests(TestCase):
    def test_state_persists_destination_window_and_reservation(self):
        start = timezone.now()
        state = WhatsAppThrottleState.objects.create(
            destination='descontos.bot',
            window_started_at=start,
            last_reserved_at=start + timedelta(seconds=1),
            window_count=1,
        )

        stored = WhatsAppThrottleState.objects.get(pk=state.pk)

        self.assertEqual(stored.destination, 'descontos.bot')
        self.assertEqual(stored.window_started_at, start)
        self.assertEqual(stored.last_reserved_at, start + timedelta(seconds=1))
        self.assertEqual(stored.window_count, 1)
        self.assertIsNotNone(stored.created_at)
        self.assertIsNotNone(stored.updated_at)

    def test_destination_is_unique(self):
        WhatsAppThrottleState.objects.create(destination='descontos.bot')

        with self.assertRaises(IntegrityError):
            WhatsAppThrottleState.objects.create(destination='descontos.bot')
