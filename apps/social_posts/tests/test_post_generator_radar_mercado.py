"""Sprint 7 - Tarefa 7.2: radar de mercado (Sprint 6) como pauta preferencial.

`_get_ranked_offers` (usado por `generate_story`/`generate_feed_post`/
`generate_carousel`) deve priorizar ofertas de categorias com `escore_venda`
alto no radar de vendas do dia, mas nunca quebrar a geração quando o radar
está desligado, sem cobertura ou com erro (fallback silencioso para o
ranking original por desconto/preço).
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.radar_mercado import RadarMercadoResult
from apps.offers.models import Category, Offer
from apps.social_posts.services.image_renderer import RenderedAsset
from apps.social_posts.services.post_generator import generate_story


class RadarMercadoPriorityTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.categoria_casa = Category.objects.create(code='casa', name='Casa e Cozinha')
        self.categoria_tech = Category.objects.create(code='tech', name='Tecnologia')

        # offer_tech tem desconto maior (ranking original venceria por -discount_pct)
        self.offer_tech = self._make_offer('tech-1', discount=Decimal('60.00'), category=self.categoria_tech)
        self.offer_casa = self._make_offer('casa-1', discount=Decimal('20.00'), category=self.categoria_casa)

    def _make_offer(self, suffix: str, discount: Decimal, category: Category) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=f'ml-{suffix}',
            title=f'Título oferta {suffix}',
            normalized_title=f'titulo oferta {suffix}',
            offer_hash=f'hash-{suffix}',
            slug=f'titulo-oferta-{suffix}',
            category=category,
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=discount,
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def _generate_top1(self):
        with patch(
            'apps.social_posts.services.post_generator.render_story_asset',
            return_value=RenderedAsset(path='/tmp/fake-story.png'),
        ):
            return generate_story(top=1)

    def test_radar_enabled_boosts_top_category_over_bigger_discount(self):
        radar = RadarMercadoResult(
            enabled=True,
            collected_at=timezone.now().isoformat(),
            category_scores={'casa': 1.0, 'tech': 0.0},
        )
        with patch('apps.social_posts.services.post_generator.collect_radar_mercado', return_value=radar):
            post = self._generate_top1()

        self.assertEqual(post.primary_offer_id, self.offer_casa.id)

    def test_radar_disabled_keeps_original_discount_ranking(self):
        radar = RadarMercadoResult(enabled=False, collected_at=timezone.now().isoformat())
        with patch('apps.social_posts.services.post_generator.collect_radar_mercado', return_value=radar):
            post = self._generate_top1()

        self.assertEqual(post.primary_offer_id, self.offer_tech.id)

    def test_radar_without_category_scores_keeps_original_ranking(self):
        radar = RadarMercadoResult(enabled=True, collected_at=timezone.now().isoformat())
        with patch('apps.social_posts.services.post_generator.collect_radar_mercado', return_value=radar):
            post = self._generate_top1()

        self.assertEqual(post.primary_offer_id, self.offer_tech.id)

    def test_radar_error_falls_back_silently_to_original_ranking(self):
        with patch(
            'apps.social_posts.services.post_generator.collect_radar_mercado',
            side_effect=RuntimeError('shopee indisponível'),
        ):
            post = self._generate_top1()

        self.assertEqual(post.primary_offer_id, self.offer_tech.id)
