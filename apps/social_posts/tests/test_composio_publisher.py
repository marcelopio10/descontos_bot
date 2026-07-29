from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.social_posts.models import InstagramPost
from apps.social_posts.services import composio_publisher
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    ComposioPublishUnknownError,
    publish_post,
    publish_story,
)


class ComposioPublisherTests(TestCase):
    def setUp(self):
        marketplace = Marketplace.objects.create(
            name='Amazon', code='amazon', base_url='https://www.amazon.com.br',
            is_active=True, affiliate_enabled=True, affiliate_tag='desconto.bot-20',
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=marketplace, external_id='B0TESTE123', title='Oferta de teste',
            normalized_title='oferta de teste', offer_hash='hash-composio-publisher',
            slug='oferta-teste', asin='B0TESTE123', current_price=Decimal('75.00'),
            original_price=Decimal('140.00'), discount_pct=Decimal('46.00'),
            product_url='https://www.amazon.com.br/dp/B0TESTE123',
            affiliate_url='https://www.amazon.com.br/dp/B0TESTE123',
            image_url='https://example.com/img.jpg', is_active=True,
            first_seen_at=now, last_seen_at=now, price_collected_at=now,
        )

    def _image(self, directory: str, name: str = 'asset.png', size=(1080, 1080)) -> str:
        path = Path(directory) / name
        Image.new('RGB', size, color=(255, 128, 0)).save(path)
        return str(path)

    def _post(self, *, post_format: str, status: str, asset_path: str) -> InstagramPost:
        return InstagramPost.objects.create(
            format=post_format, status=status, primary_offer=self.offer,
            asset_paths=[asset_path], caption='Legenda de teste',
            sticker_target_url='https://descontos-bot.vercel.app/r?slug=oferta-teste',
        )

    def _fake_execute(self, calls, *, permalink='https://www.instagram.com/p/teste/'):
        def execute(action, payload):
            calls.append((action, payload.copy()))
            if action == composio_publisher.PROFILE_ACTION:
                return {'id': 'ig-user-1', 'username': 'descontos.bot'}
            if action == composio_publisher.CREATE_ACTION:
                return {'id': 'container-1'}
            if action == composio_publisher.PUBLISH_ACTION:
                return {'id': 'media-1'}
            if action == composio_publisher.MEDIA_ACTION:
                return {
                    'id': 'media-1', 'username': 'descontos.bot',
                    'caption': 'Legenda de teste', 'permalink': permalink,
                    'media_type': 'IMAGE', 'timestamp': '2026-07-27T12:00:00+0000',
                }
            raise AssertionError(action)
        return execute

    @override_settings(
        INSTAGRAM_PUBLISH_DRY_RUN=False,
        COMPOSIO_PROJECT_NAME='descontos-bot', COMPOSIO_USER_ID='marcelo',
        COMPOSIO_INSTAGRAM_ACCOUNT_ID='ca_descontos',
        INSTAGRAM_EXPECTED_USERNAME='descontos.bot',
    )
    def test_publish_feed_pins_account_and_reconciles_media(self):
        calls = []
        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=self._fake_execute(calls)):
                result = publish_post(post)

        self.assertEqual(result.permalink, 'https://www.instagram.com/p/teste/')
        self.assertEqual(
            [item[0] for item in calls],
            [composio_publisher.PROFILE_ACTION, composio_publisher.CREATE_ACTION,
             composio_publisher.PUBLISH_ACTION, composio_publisher.MEDIA_ACTION],
        )
        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.POSTED)
        self.assertEqual(post.publish_state, 'confirmed')
        self.assertEqual(post.instagram_media_id, 'media-1')
        self.assertEqual(post.instagram_permalink, result.permalink)
        self.assertEqual(post.publication_receipt['status'], 'PUBLICADA')

    @override_settings(
        INSTAGRAM_PUBLISH_DRY_RUN=False,
        COMPOSIO_PROJECT_NAME='descontos-bot', COMPOSIO_USER_ID='marcelo',
        COMPOSIO_INSTAGRAM_ACCOUNT_ID='ca_descontos',
        INSTAGRAM_EXPECTED_USERNAME='descontos.bot',
    )
    def test_publish_story_uses_stories_media_type(self):
        calls = []
        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.STORY,
                status=InstagramPost.Status.AWAITING_POST,
                asset_path=self._image(tmpdir, 'story.png', size=(1080, 1920)),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=self._fake_execute(calls)):
                publish_post(post)

        create_payload = calls[1][1]
        self.assertEqual(create_payload['media_type'], 'STORIES')
        self.assertEqual(calls[2][1]['creation_id'], 'container-1')

    @override_settings(INSTAGRAM_PUBLISH_DRY_RUN=True)
    def test_dry_run_does_not_require_credentials_or_change_status(self):
        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            result = publish_post(post)

        self.assertEqual(result.container_id, 'dry-run-container')
        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.READY)
        self.assertEqual(post.publish_state, 'not_started')

    @override_settings(
        INSTAGRAM_PUBLISH_DRY_RUN=False,
        COMPOSIO_PROJECT_NAME='descontos-bot', COMPOSIO_USER_ID='marcelo',
        COMPOSIO_INSTAGRAM_ACCOUNT_ID='ca_descontos',
        INSTAGRAM_EXPECTED_USERNAME='descontos.bot',
    )
    def test_wrong_account_fails_before_container(self):
        def wrong_profile(action, payload):
            self.assertEqual(action, composio_publisher.PROFILE_ACTION)
            return {'id': 'other', 'username': 'outra.conta'}

        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=wrong_profile):
                with self.assertRaises(ComposioPublishError) as ctx:
                    publish_post(post)

        self.assertEqual(ctx.exception.stage, 'preflight')
        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.READY)
        self.assertEqual(post.publish_state, 'not_started')

    @override_settings(
        INSTAGRAM_PUBLISH_DRY_RUN=False,
        COMPOSIO_PROJECT_NAME='descontos-bot', COMPOSIO_USER_ID='marcelo',
        COMPOSIO_INSTAGRAM_ACCOUNT_ID='ca_descontos',
        INSTAGRAM_EXPECTED_USERNAME='descontos.bot',
    )
    def test_reconciliation_unknown_does_not_mark_posted(self):
        calls = []

        def unknown_media(action, payload):
            if action == composio_publisher.PROFILE_ACTION:
                return {'id': 'ig-user-1', 'username': 'descontos.bot'}
            if action == composio_publisher.CREATE_ACTION:
                return {'id': 'container-1'}
            if action == composio_publisher.PUBLISH_ACTION:
                return {'id': 'media-1'}
            calls.append(action)
            return {'id': 'media-1', 'username': 'descontos.bot', 'caption': 'outra', 'permalink': 'https://www.instagram.com/p/teste/'}

        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=unknown_media):
                with self.assertRaises(ComposioPublishUnknownError):
                    publish_post(post)

        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.READY)
        self.assertEqual(post.publish_state, 'unknown')
        self.assertEqual(calls, [composio_publisher.MEDIA_ACTION])

    def test_publish_story_rejects_feed_post(self):
        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            with self.assertRaises(ComposioPublishError) as ctx:
                publish_story(post, dry_run=True)
        self.assertEqual(ctx.exception.stage, 'precheck')


class InstagramPublishCommandTests(TestCase):
    def test_real_publish_requires_explicit_confirmation(self):
        with self.assertRaises(CommandError):
            call_command('publish_instagram_post', '--post-id', '999999')
