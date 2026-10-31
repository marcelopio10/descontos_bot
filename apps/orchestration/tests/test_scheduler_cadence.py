from io import StringIO
from typing import cast

from django.core.management import call_command
from django.test import TestCase

from apps.distribution.models import SocialChannel
from apps.orchestration.management.commands.consumir_fila_whatsapp import Command as ConsumeCommand
from apps.orchestration.management.commands.run_bot import Command as RunBotCommand
from apps.orchestration.services.scheduler import (
    ChannelCadenceConfig,
    apply_channel_cadence,
    get_channel_cadence_config,
)
from apps.panel.models import Setting


class ChannelCadenceTests(TestCase):
    def test_default_configuration_uses_hard_floor_of_five(self):
        config = get_channel_cadence_config()

        self.assertEqual(config.min_items_per_cycle, 5)
        self.assertEqual(config.max_items_per_cycle, 20)

    def test_configuration_validates_floor_against_maximum_and_global_limit(self):
        Setting.objects.create(key='channel_items_min_per_cycle', value='5')
        Setting.objects.create(key='channel_items_max_per_cycle', value='20')
        Setting.objects.create(key='offer_limit_global', value='20')

        config = get_channel_cadence_config()

        self.assertEqual(config.min_items_per_cycle, 5)
        self.assertEqual(config.max_items_per_cycle, 20)

    def test_configuration_rejects_invalid_floor(self):
        invalid_values = (
            ('0', '20', '20'),
            ('21', '20', '30'),
            ('21', '30', '20'),
            ('not-an-int', '20', '20'),
            ('5', 'not-an-int', '20'),
            ('5', '20', 'not-an-int'),
        )
        for minimum, maximum, global_limit in invalid_values:
            with self.subTest(
                minimum=minimum,
                maximum=maximum,
                global_limit=global_limit,
            ):
                Setting.objects.update_or_create(
                    key='channel_items_min_per_cycle',
                    defaults={'value': minimum},
                )
                Setting.objects.update_or_create(
                    key='channel_items_max_per_cycle',
                    defaults={'value': maximum},
                )
                Setting.objects.update_or_create(
                    key='offer_limit_global',
                    defaults={'value': global_limit},
                )

                with self.assertRaises(ValueError):
                    get_channel_cadence_config()

    def test_seed_settings_creates_whatsapp_policy_defaults(self):
        call_command('seed_settings', stdout=StringIO())

        expected = {
            'channel_items_min_per_cycle': '5',
            'channel_items_max_per_cycle': '20',
            'offer_books_whatsapp_allowed': 'false',
            'offer_title_repeat_hours': '72',
            'offer_family_spacing_enabled': 'true',
            'offer_family_cooldown_hours': '24',
            'offer_family_window_hours': '24',
            'offer_family_max_window_sends': '1',
            'offer_observer_candidate_multiplier': '5',
        }
        actual = dict(
            Setting.objects.filter(key__in=expected).values_list('key', 'value')
        )

        self.assertEqual(actual, expected)

    def test_seed_settings_preserves_existing_operational_values(self):
        existing = {
            'channel_items_min_per_cycle': '7',
            'channel_items_max_per_cycle': '9',
            'offer_books_whatsapp_allowed': 'true',
        }
        for key, value in existing.items():
            Setting.objects.create(key=key, value=value)

        call_command('seed_settings', stdout=StringIO())

        actual = dict(
            Setting.objects.filter(key__in=existing).values_list('key', 'value')
        )
        self.assertEqual(actual, existing)

    def test_requested_limit_cannot_exceed_channel_maximum(self):
        result = apply_channel_cadence(
            list(range(100)),
            config=ChannelCadenceConfig(
                min_items_per_cycle=1,
                max_items_per_cycle=20,
            ),
            requested_limit=500,
        )

        self.assertEqual(len(result.items), 20)
        self.assertTrue(result.capped)
        self.assertEqual(result.limit, 20)

    def test_requested_limit_can_reduce_but_not_raise_channel_maximum(self):
        result = apply_channel_cadence(
            list(range(100)),
            config=ChannelCadenceConfig(
                min_items_per_cycle=1,
                max_items_per_cycle=20,
            ),
            requested_limit=5,
        )

        self.assertEqual(len(result.items), 5)
        self.assertTrue(result.capped)
        self.assertEqual(result.limit, 5)

    def test_invalid_requested_limit_fails_closed(self):
        for requested_limit in (0, -1, True, 1.5):
            with self.subTest(requested_limit=requested_limit):
                with self.assertRaises(ValueError):
                    apply_channel_cadence(
                        [],
                        config=ChannelCadenceConfig(
                            min_items_per_cycle=1,
                            max_items_per_cycle=20,
                        ),
                        requested_limit=cast(int, requested_limit),
                    )

    def test_consuming_command_subordinates_manual_limit_to_cadence(self):
        command = ConsumeCommand(stdout=StringIO())
        channel = cast(SocialChannel, type('Channel', (), {'code': 'whatsapp_homolog'})())

        items = command._apply_channel_cadence(
            channel=channel,
            items=list(range(100)),
            requested_limit=500,
        )

        self.assertEqual(len(items), 20)

    def test_run_bot_subordinates_manual_limit_to_cadence(self):
        command = RunBotCommand(stdout=StringIO())
        channel = cast(SocialChannel, type('Channel', (), {'code': 'whatsapp_homolog'})())

        items = command._apply_channel_cadence(
            channel=channel,
            items=list(range(100)),
            requested_limit=500,
        )

        self.assertEqual(len(items), 20)
