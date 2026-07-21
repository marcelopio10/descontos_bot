"""Sprint 7 - Tarefa 7.2: teto diário de geração de conteúdo Instagram.

Cobre a política em `apps.social_posts.services.politica_cadencia` isolada
(sem passar pelos geradores de asset) e a aplicação real dela dentro de
`post_generator` (Tarefa 7.1 — reativação da geração precisa ficar atrás
desse teto).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.image_renderer import RenderedAsset
from apps.social_posts.services.politica_cadencia import (
    CadenciaExcedidaError,
    DEFAULT_FEED_OR_CAROUSEL_DAILY_LIMIT,
    DEFAULT_STORY_DAILY_LIMIT,
    FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY,
    STORY_DAILY_LIMIT_SETTING_KEY,
    get_cadencia_config,
    pode_gerar_feed_ou_carrossel,
    pode_gerar_story,
)
from apps.social_posts.services.post_generator import generate_feed_post, generate_story_for_offer


class PoliticaCadenciaTestsMixin:
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

    def _make_post(self, offer: Offer, post_format: str) -> InstagramPost:
        return InstagramPost.objects.create(
            format=post_format,
            status=InstagramPost.Status.READY,
            primary_offer=offer,
            asset_paths=['fake.png'],
            caption='caption',
            sticker_target_url='https://example.com/afiliado',
        )


class GetCadenciaConfigTests(PoliticaCadenciaTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_defaults_match_rotina_editorial_doc(self):
        # docs/ROTINA_EDITORIAL_INSTAGRAM.md secao 2: 3 stories/dia + 1 feed-ou-carrossel/dia.
        config = get_cadencia_config()
        self.assertEqual(config.story_daily_limit, DEFAULT_STORY_DAILY_LIMIT)
        self.assertEqual(config.feed_or_carousel_daily_limit, DEFAULT_FEED_OR_CAROUSEL_DAILY_LIMIT)
        self.assertEqual(DEFAULT_STORY_DAILY_LIMIT, 3)
        self.assertEqual(DEFAULT_FEED_OR_CAROUSEL_DAILY_LIMIT, 1)

    def test_settings_override_limits_without_redeploy(self):
        Setting.objects.create(key=STORY_DAILY_LIMIT_SETTING_KEY, value='5')
        Setting.objects.create(key=FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY, value='2')
        config = get_cadencia_config()
        self.assertEqual(config.story_daily_limit, 5)
        self.assertEqual(config.feed_or_carousel_daily_limit, 2)


class PodeGerarStoryTests(PoliticaCadenciaTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_allows_generation_below_teto(self):
        for i in range(DEFAULT_STORY_DAILY_LIMIT - 1):
            self._make_post(self._make_offer(f'story-{i}'), InstagramPost.Format.STORY)
        self.assertTrue(pode_gerar_story())

    def test_blocks_generation_at_teto(self):
        for i in range(DEFAULT_STORY_DAILY_LIMIT):
            self._make_post(self._make_offer(f'story-{i}'), InstagramPost.Format.STORY)
        self.assertFalse(pode_gerar_story())

    def test_zero_limit_setting_always_blocks(self):
        Setting.objects.create(key=STORY_DAILY_LIMIT_SETTING_KEY, value='0')
        self.assertFalse(pode_gerar_story())

    def test_only_counts_stories_created_today(self):
        post = self._make_post(self._make_offer('story-old'), InstagramPost.Format.STORY)
        InstagramPost.objects.filter(pk=post.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1),
        )
        self.assertTrue(pode_gerar_story())

    def test_feed_and_carousel_posts_do_not_count_against_story_teto(self):
        for i in range(DEFAULT_STORY_DAILY_LIMIT):
            self._make_post(self._make_offer(f'feed-{i}'), InstagramPost.Format.FEED)
        self.assertTrue(pode_gerar_story())


class PodeGerarFeedOuCarrosselTests(PoliticaCadenciaTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_allows_first_feed_or_carousel_of_the_day(self):
        self.assertTrue(pode_gerar_feed_ou_carrossel())

    def test_feed_and_carousel_share_the_same_daily_teto(self):
        self._make_post(self._make_offer('feed-1'), InstagramPost.Format.FEED)
        # Teto default é 1: já usado por um FEED, então CAROUSEL também é bloqueado.
        self.assertFalse(pode_gerar_feed_ou_carrossel())

    def test_setting_override_raises_the_shared_teto(self):
        Setting.objects.create(key=FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY, value='2')
        self._make_post(self._make_offer('feed-1'), InstagramPost.Format.FEED)
        self.assertTrue(pode_gerar_feed_ou_carrossel())


class PostGeneratorRespectsCadenciaTests(PoliticaCadenciaTestsMixin, TestCase):
    """Prova de que a reativação (Tarefa 7.1) fica atrás do teto (Tarefa 7.2)."""

    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_generate_story_for_offer_creates_post_when_under_teto(self):
        offer = self._make_offer('nova-1')
        with patch(
            'apps.social_posts.services.post_generator.render_story_asset',
            return_value=RenderedAsset(path='/tmp/fake-story.png'),
        ):
            post = generate_story_for_offer(offer)

        self.assertEqual(InstagramPost.objects.filter(format=InstagramPost.Format.STORY).count(), 1)
        self.assertEqual(post.primary_offer_id, offer.id)

    def test_generate_story_for_offer_raises_when_teto_atingido(self):
        for i in range(DEFAULT_STORY_DAILY_LIMIT):
            self._make_post(self._make_offer(f'story-{i}'), InstagramPost.Format.STORY)

        nova_offer = self._make_offer('nova-extra')
        with self.assertRaises(CadenciaExcedidaError):
            generate_story_for_offer(nova_offer)
        # Nao criou post algum para a oferta nova: recusa limpa, sem asset gerado.
        self.assertFalse(
            InstagramPost.objects.filter(primary_offer=nova_offer).exists(),
        )

    def test_generate_story_for_offer_returns_existing_without_counting_against_teto(self):
        """Reconsultar uma story ja gerada e idempotente e nao deve ser bloqueado
        pelo teto (ver comentario em post_generator.generate_story_for_offer)."""
        offer = self._make_offer('idempotente-1')
        existing = self._make_post(offer, InstagramPost.Format.STORY)
        for i in range(DEFAULT_STORY_DAILY_LIMIT):
            self._make_post(self._make_offer(f'story-extra-{i}'), InstagramPost.Format.STORY)

        post = generate_story_for_offer(offer)
        self.assertEqual(post.pk, existing.pk)

    def test_generate_feed_post_raises_when_teto_atingido(self):
        self._make_post(self._make_offer('feed-ja-gerado'), InstagramPost.Format.CAROUSEL)

        with self.assertRaises(CadenciaExcedidaError):
            generate_feed_post(top=1)
