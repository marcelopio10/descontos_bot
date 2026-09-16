from io import StringIO
from typing import cast

from django.test import TestCase

from apps.distribution.models import SocialChannel
from apps.orchestration.management.commands.consumir_fila_whatsapp import Command as ConsumeCommand
from apps.orchestration.management.commands.run_bot import Command as RunBotCommand
from apps.orchestration.services.scheduler import (
    ChannelCadenceConfig,
    apply_channel_cadence,
)


class ChannelCadenceTests(TestCase):
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
