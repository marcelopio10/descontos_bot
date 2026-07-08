from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.social_posts.models import InstagramPost
from apps.social_posts.services import composio_publisher
from apps.social_posts.services.composio_publisher import ComposioPublishError, publish_post, publish_story


class ComposioPublisherTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
            is_active=True,
            affiliate_enabled=True,
            affiliate_tag='desconto.bot-20',
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            external_id='B0TESTE123',
            title='Oferta de teste',
            normalized_title='oferta de teste',
            offer_hash='hash-composio-publisher',
            slug='oferta-teste',
            asin='B0TESTE123',
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=Decimal('46.00'),
            product_url='https://www.amazon.com.br/dp/B0TESTE123',
            affiliate_url='https://www.amazon.com.br/dp/B0TESTE123',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def _image(self, directory: str, name: str = 'asset.png') -> str:
        path = Path(directory) / name
        Image.new('RGB', (1080, 1080), color=(255, 128, 0)).save(path)
        return str(path)

    def _post(self, *, post_format: str, status: str, asset_path: str) -> InstagramPost:
        return InstagramPost.objects.create(
            format=post_format,
            status=status,
            primary_offer=self.offer,
            asset_paths=[asset_path],
            caption='Legenda de teste',
            sticker_target_url='https://descontos-bot.vercel.app/r?slug=oferta-teste',
        )

    @override_settings(INSTAGRAM_USER_ID='27176727021981283', INSTAGRAM_PUBLISH_DRY_RUN=False)
    def test_publish_feed_post_uses_composio_without_story_media_type(self):
        calls = []

        def fake_execute(action, payload):
            calls.append((action, payload.copy()))
            if action == composio_publisher.CREATE_ACTION:
                return {'successful': True, 'data': {'id': 'container-feed'}}
            return {'successful': True, 'data': {'id': 'media-feed'}}

        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=fake_execute):
                result = publish_post(post)

        self.assertEqual(result.container_id, 'container-feed')
        self.assertEqual(result.media_id, 'media-feed')
        self.assertEqual(calls[0][0], composio_publisher.CREATE_ACTION)
        self.assertEqual(calls[0][1]['ig_user_id'], '27176727021981283')
        self.assertIn('image_file', calls[0][1])
        self.assertNotIn('media_type', calls[0][1])
        self.assertEqual(calls[0][1]['caption'], 'Legenda de teste')
        self.assertEqual(calls[1][0], composio_publisher.PUBLISH_ACTION)
        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.POSTED)
        self.assertEqual(post.instagram_media_id, 'media-feed')

    @override_settings(INSTAGRAM_USER_ID='27176727021981283', INSTAGRAM_PUBLISH_DRY_RUN=False)
    def test_publish_story_accepts_run_bot_awaiting_post_and_sets_stories_media_type(self):
        calls = []

        def fake_execute(action, payload):
            calls.append((action, payload.copy()))
            if action == composio_publisher.CREATE_ACTION:
                return {'successful': True, 'data': {'id': 'container-story'}}
            return {'successful': True, 'data': {'id': 'media-story'}}

        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.STORY,
                status=InstagramPost.Status.AWAITING_POST,
                asset_path=self._image(tmpdir, 'story.png'),
            )
            with patch.object(composio_publisher, '_composio_execute', side_effect=fake_execute):
                result = publish_post(post)

        self.assertEqual(result.container_id, 'container-story')
        self.assertEqual(calls[0][1]['media_type'], 'STORIES')
        self.assertEqual(calls[1][1]['creation_id'], 'container-story')
        post.refresh_from_db()
        self.assertEqual(post.status, InstagramPost.Status.POSTED)
        self.assertEqual(post.instagram_media_id, 'media-story')

    def test_publish_story_rejects_feed_post_even_as_compatibility_wrapper(self):
        with TemporaryDirectory() as tmpdir:
            post = self._post(
                post_format=InstagramPost.Format.FEED,
                status=InstagramPost.Status.READY,
                asset_path=self._image(tmpdir),
            )

            with self.assertRaises(ComposioPublishError) as ctx:
                publish_story(post, dry_run=True)

        self.assertEqual(ctx.exception.stage, 'precheck')
        self.assertIn('STORY', str(ctx.exception))
