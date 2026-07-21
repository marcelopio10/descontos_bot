"""Sprint 7 - Tarefa 7.1 (achado C4): comandos manuais reativados.

Até 2026-07-09 os três comandos abaixo imprimiam um aviso de "desativado" e
saíam (`return`) antes de qualquer lógica real — inclusive com uma alegação
falsa em `generate_instagram_story` de que "a geração automática (run_bot)
segue ativa" (também estava desativada, mesmo commit). Este arquivo prova
que os três voltam a gerar `InstagramPost` de verdade e que a mensagem falsa
não aparece mais.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.image_renderer import RenderedAsset


class ManualInstagramCommandsReactivationTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def _make_offer(self, suffix: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=f'ml-{suffix}',
            title=f'Título oferta {suffix}',
            normalized_title=f'titulo oferta {suffix}',
            offer_hash=f'hash-{suffix}',
            slug=f'titulo-oferta-{suffix}',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_generate_instagram_story_no_longer_claims_run_bot_is_active(self):
        self._make_offer('story-1')
        out = StringIO()

        with patch(
            'apps.social_posts.services.post_generator.render_story_asset',
            return_value=RenderedAsset(path='/tmp/fake-story.png'),
        ):
            call_command('generate_instagram_story', '--top', '1', stdout=out)

        text = out.getvalue()
        self.assertNotIn('desativada', text)
        self.assertNotIn('A geração automática (run_bot) segue ativa', text)
        self.assertIn('Story Instagram #', text)
        self.assertEqual(InstagramPost.objects.filter(format=InstagramPost.Format.STORY).count(), 1)

    def test_generate_instagram_post_creates_feed_post(self):
        self._make_offer('feed-1')
        out = StringIO()

        with patch(
            'apps.social_posts.services.post_generator.render_feed_asset',
            return_value=RenderedAsset(path='/tmp/fake-feed.png'),
        ):
            call_command('generate_instagram_post', '--top', '1', stdout=out)

        text = out.getvalue()
        self.assertNotIn('desativada', text)
        self.assertIn('Post Instagram #', text)
        self.assertEqual(InstagramPost.objects.filter(format=InstagramPost.Format.FEED).count(), 1)

    def test_generate_instagram_carousel_creates_carousel_post(self):
        for i in range(5):
            self._make_offer(f'carousel-{i}')
        out = StringIO()

        with patch(
            'apps.social_posts.services.post_generator.render_carousel_assets',
            return_value=[RenderedAsset(path=f'/tmp/fake-carousel-{i}.png') for i in range(5)],
        ):
            call_command('generate_instagram_carousel', '--count', '5', stdout=out)

        text = out.getvalue()
        self.assertNotIn('desativada', text)
        self.assertIn('Carrossel Instagram #', text)
        self.assertEqual(InstagramPost.objects.filter(format=InstagramPost.Format.CAROUSEL).count(), 1)
