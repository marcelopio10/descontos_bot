"""Sprint 7 - Tarefa 7.1 (achado C4): reativação da geração de conteúdo Instagram.

Até 2026-07-09 (commit f359320) a geração automática ficava atrás de um
`return` incondicional em `Command._generate_instagram_posts_for_new_offers`
e `Command._generate_instagram_story` — nenhuma das duas nunca chegava a
chamar `generate_story_for_offer`. Este arquivo prova que, reativadas, elas
voltam a criar `InstagramPost` de verdade, respeitando o teto diário de
`apps.social_posts.services.politica_cadencia` (Tarefa 7.2) para não voltar
a gerar em rajada.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.orchestration.management.commands.run_bot import Command
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.image_renderer import RenderedAsset
from apps.social_posts.services.politica_cadencia import DEFAULT_STORY_DAILY_LIMIT


class RunBotInstagramGenerationTestsMixin:
    def _make_offer(self, suffix: str, *, last_seen_at=None) -> Offer:
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
            last_seen_at=last_seen_at or now,
            price_collected_at=now,
        )

    def _render_patch(self):
        return patch(
            'apps.social_posts.services.post_generator.render_story_asset',
            return_value=RenderedAsset(path='/tmp/fake-story.png'),
        )


class GenerateInstagramPostsForNewOffersTests(RunBotInstagramGenerationTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_reactivated_generation_creates_instagram_post_for_new_offer(self):
        offer = self._make_offer('nova-1')
        cmd = Command(stdout=StringIO())

        with self._render_patch():
            cmd._generate_instagram_posts_for_new_offers()

        self.assertEqual(InstagramPost.objects.count(), 1)
        post = InstagramPost.objects.get()
        self.assertEqual(post.format, InstagramPost.Format.STORY)
        self.assertEqual(post.primary_offer_id, offer.id)

    def test_old_offers_outside_window_are_not_used(self):
        old_offer = self._make_offer(
            'velha-1', last_seen_at=timezone.now() - timezone.timedelta(hours=48),
        )
        out = StringIO()
        cmd = Command(stdout=out)

        with self._render_patch():
            cmd._generate_instagram_posts_for_new_offers()

        self.assertEqual(InstagramPost.objects.count(), 0)
        self.assertIn('Nenhuma oferta nova', out.getvalue())

    def test_generation_stops_at_daily_teto_instead_of_looping_through_all_candidates(self):
        """Tarefa 7.2: a reativação (7.1) fica atrás do teto diário — não volta a
        gerar em rajada mesmo com muitas ofertas novas elegíveis no mesmo ciclo."""
        total_candidatas = DEFAULT_STORY_DAILY_LIMIT + 2
        for i in range(total_candidatas):
            self._make_offer(f'nova-{i}')
        out = StringIO()
        cmd = Command(stdout=out)

        with self._render_patch():
            cmd._generate_instagram_posts_for_new_offers()

        self.assertEqual(InstagramPost.objects.count(), DEFAULT_STORY_DAILY_LIMIT)
        self.assertIn('Cadência Instagram', out.getvalue())


class GenerateInstagramStorySingleOfferTests(RunBotInstagramGenerationTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )

    def test_reactivated_single_offer_generation_creates_instagram_post(self):
        offer = self._make_offer('unica-1')
        out = StringIO()
        cmd = Command(stdout=out)

        with self._render_patch():
            cmd._generate_instagram_story(offer)

        self.assertEqual(InstagramPost.objects.filter(format=InstagramPost.Format.STORY).count(), 1)
        self.assertIn('Story Instagram pronto', out.getvalue())

    def test_single_offer_generation_skips_cleanly_when_teto_atingido(self):
        for i in range(DEFAULT_STORY_DAILY_LIMIT):
            InstagramPost.objects.create(
                format=InstagramPost.Format.STORY,
                status=InstagramPost.Status.READY,
                primary_offer=self._make_offer(f'story-{i}'),
                asset_paths=['fake.png'],
                caption='caption',
                sticker_target_url='https://example.com/afiliado',
            )
        offer = self._make_offer('extra-1')
        out = StringIO()
        cmd = Command(stdout=out)

        with self._render_patch():
            cmd._generate_instagram_story(offer)

        # Recusa limpa: nenhuma exceção propagada, nenhum post extra criado.
        self.assertEqual(InstagramPost.objects.filter(primary_offer=offer).count(), 0)
        self.assertIn('Story Instagram não gerado', out.getvalue())
