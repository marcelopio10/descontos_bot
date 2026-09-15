from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.db import IntegrityError, OperationalError
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


class WhatsAppRateLimiterPersistenceTests(TestCase):
    @patch('apps.distribution.services.whatsapp_rate_limiter.timezone')
    def test_second_process_sees_slot_reserved_by_first_process(self, timezone_mock):
        start = datetime(2026, 9, 15, 12, 0, tzinfo=dt_timezone.utc)
        timezone_mock.now.side_effect = [start, start + timedelta(seconds=1)]
        from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter

        first = WhatsAppRateLimiter(min_interval_seconds=15, max_sends_per_hour=20)
        second = WhatsAppRateLimiter(min_interval_seconds=15, max_sends_per_hour=20)

        self.assertEqual(first._try_reserve_slot('descontos.bot'), 0)
        self.assertGreaterEqual(second._try_reserve_slot('descontos.bot'), 14)
        self.assertEqual(WhatsAppThrottleState.objects.count(), 1)

    @patch('apps.distribution.services.whatsapp_rate_limiter.timezone')
    def test_twenty_first_slot_waits_until_hour_window_expires(self, timezone_mock):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=dt_timezone.utc)
        timezone_mock.now.return_value = now
        WhatsAppThrottleState.objects.create(
            destination='descontos.bot',
            window_started_at=now - timedelta(minutes=10),
            last_reserved_at=now - timedelta(seconds=30),
            window_count=20,
        )
        from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter

        wait_seconds = WhatsAppRateLimiter(
            min_interval_seconds=15,
            max_sends_per_hour=20,
        )._try_reserve_slot('descontos.bot')

        self.assertGreater(wait_seconds, 0)
        self.assertEqual(WhatsAppThrottleState.objects.get().window_count, 20)

    @patch('apps.distribution.services.whatsapp_rate_limiter.timezone')
    def test_different_destinations_have_independent_state(self, timezone_mock):
        timezone_mock.now.return_value = datetime(2026, 9, 15, 12, 0, tzinfo=dt_timezone.utc)
        from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter

        limiter = WhatsAppRateLimiter(min_interval_seconds=15, max_sends_per_hour=20)

        self.assertEqual(limiter._try_reserve_slot('descontos.bot'), 0)
        self.assertEqual(limiter._try_reserve_slot('whatsapp_principal'), 0)
        self.assertEqual(WhatsAppThrottleState.objects.count(), 2)

    def test_zero_hourly_limit_is_normalized_to_safe_positive_limit(self):
        from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter

        limiter = WhatsAppRateLimiter(max_sends_per_hour=0)

        self.assertEqual(limiter._max_sends_per_hour, 1)

    def test_locked_database_is_retried_at_most_five_times(self):
        from apps.distribution.services.whatsapp_rate_limiter import WhatsAppRateLimiter

        limiter = WhatsAppRateLimiter()
        with (
            patch.object(
                limiter,
                '_try_reserve_slot_once',
                side_effect=[OperationalError('database is locked')] * 4 + [0],
            ) as reserve,
            patch('apps.distribution.services.whatsapp_rate_limiter.time.sleep'),
        ):
            self.assertEqual(limiter._try_reserve_slot('descontos.bot'), 0)

        self.assertEqual(reserve.call_count, 5)
