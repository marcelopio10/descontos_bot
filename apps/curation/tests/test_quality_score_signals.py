"""Sprint 6 — sinais opcionais de observer_context (Tarefa 6.2, achado P3) e
market_radar (Tarefa 6.1, achado P7) em quality_score/quality_score_breakdown.

Cobertura central: (1) sem contexto, o comportamento é idêntico ao de antes
desta tarefa (prova de rollback); (2) com contexto/radar "fortes", o score
sobe um pouco; (3) sem correspondência, nada muda.
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.quality_score import quality_score, quality_score_breakdown
from apps.marketplaces.models import Marketplace
from apps.offers.models import Category, Offer


class QualityScoreSignalsTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
            is_active=True,
        )
        self.category = Category.objects.create(code='tecnologia_cotidiana_qa', name='Tecnologia Cotidiana', weight=7)
        self.now = timezone.now()

    _UNSET = object()

    def _make_offer(self, *, discount_pct='75.00', external_id='signal-offer', category=_UNSET) -> Offer:
        return Offer.objects.create(
            marketplace=self.marketplace,
            category=self.category if category is self._UNSET else category,
            external_id=external_id,
            title=f'Produto {external_id}',
            normalized_title=f'produto {external_id}',
            offer_hash=f'hash-{external_id}',
            slug=f'produto-{external_id}',
            current_price=Decimal('99.90'),
            original_price=Decimal('399.90'),
            discount_pct=Decimal(discount_pct),
            product_url=f'https://example.com/{external_id}',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=self.now,
            last_seen_at=self.now,
            price_collected_at=self.now,
        )

    # --- rollback: sem contexto, comportamento idêntico -------------------

    def test_no_observer_context_and_no_market_radar_matches_default_call(self):
        offer = self._make_offer()

        explicit_none = quality_score_breakdown(offer, observer_context=None, market_radar=None)
        default_call = quality_score_breakdown(offer)

        # assertAlmostEqual (não assertEqual): a multiplicadora `recency` usa
        # timezone.now() a cada chamada, então duas chamadas separadas (mesmo
        # sem nenhum sinal novo) sempre têm um micro-delta de tempo decorrido
        # entre elas — nada a ver com observer_context/market_radar.
        self.assertAlmostEqual(explicit_none.score, default_call.score, places=3)
        self.assertEqual(explicit_none.components, default_call.components)
        self.assertNotIn('observer_bonus', explicit_none.multipliers)
        self.assertNotIn('market_radar_bonus', explicit_none.multipliers)

    def test_empty_dict_context_behaves_like_none(self):
        offer = self._make_offer()

        with_empty = quality_score_breakdown(offer, observer_context={}, market_radar={})
        without = quality_score_breakdown(offer)

        self.assertAlmostEqual(with_empty.score, without.score, places=3)
        self.assertEqual(with_empty.components, without.components)

    # --- observer_context bônus --------------------------------------------

    def test_observer_bonus_when_marketplace_is_top_observed(self):
        offer = self._make_offer()
        observer_context = {
            'marketplace_counts': {'mercadolivre': 40, 'amazon': 3},
            'editorial_label_counts': {},
        }

        breakdown = quality_score_breakdown(offer, observer_context=observer_context)

        self.assertIn('observer_bonus', breakdown.multipliers)
        self.assertGreater(breakdown.multipliers['observer_bonus'], 1.0)
        self.assertGreater(
            quality_score(offer, observer_context=observer_context),
            quality_score(offer),
        )

    def test_observer_opportunity_radar_boosts_matching_brand_and_price_band(self):
        offer = self._make_offer()
        offer.title = 'Nike Air Max Oferta'
        offer.normalized_title = 'nike air max oferta'
        offer.current_price = Decimal('47.84')
        offer.save(update_fields=['title', 'normalized_title', 'current_price'])
        observer_context = {
            'marketplace_counts': {},
            'editorial_label_counts': {},
            'opportunity_radar': {
                'brands': {'nike': 10},
                'price_bands': {'0_50': 10},
                'categories': {},
                'coupons': {},
                'marketplaces': {},
            },
        }

        breakdown = quality_score_breakdown(offer, observer_context=observer_context)

        self.assertIn('observer_bonus', breakdown.multipliers)
        self.assertGreater(breakdown.multipliers['observer_bonus'], 1.0)

    def test_observer_bonus_when_discount_tier_label_is_top_observed(self):
        offer = self._make_offer(discount_pct='75.00')  # >=70 -> desconto_70/50/30
        observer_context = {
            'marketplace_counts': {},
            'editorial_label_counts': {'desconto_70': 30, 'cupom': 2},
        }

        breakdown = quality_score_breakdown(offer, observer_context=observer_context)

        self.assertIn('observer_bonus', breakdown.multipliers)

    def test_observer_bonus_absent_without_match(self):
        offer = self._make_offer(discount_pct='25.00')  # não bate nenhuma faixa desconto_30/50/70
        observer_context = {
            'marketplace_counts': {'amazon': 50, 'shopee': 20},  # oferta é mercadolivre
            'editorial_label_counts': {'urgencia': 10},
        }

        breakdown = quality_score_breakdown(offer, observer_context=observer_context)

        self.assertNotIn('observer_bonus', breakdown.multipliers)
        self.assertAlmostEqual(breakdown.score, quality_score_breakdown(offer).score, places=3)

    def test_observer_bonus_only_considers_top_n_marketplaces(self):
        offer = self._make_offer()
        # mercadolivre é o 4º mais citado (fora do top 3) -> sem bônus.
        observer_context = {
            'marketplace_counts': {'amazon': 100, 'shopee': 90, 'magalu': 80, 'mercadolivre': 1},
            'editorial_label_counts': {},
        }

        breakdown = quality_score_breakdown(offer, observer_context=observer_context)

        self.assertNotIn('observer_bonus', breakdown.multipliers)

    # --- market_radar bônus -------------------------------------------------

    def test_market_radar_bonus_when_category_well_positioned(self):
        offer = self._make_offer()
        market_radar = {'category_scores': {'tecnologia_cotidiana_qa': 0.95}}

        breakdown = quality_score_breakdown(offer, market_radar=market_radar)

        self.assertIn('market_radar_bonus', breakdown.multipliers)
        self.assertGreater(breakdown.multipliers['market_radar_bonus'], 1.0)
        self.assertLessEqual(breakdown.multipliers['market_radar_bonus'], 1.08)

    def test_market_radar_bonus_absent_below_threshold(self):
        offer = self._make_offer()
        market_radar = {'category_scores': {'tecnologia_cotidiana_qa': 0.3}}  # abaixo do limiar (0.6)

        breakdown = quality_score_breakdown(offer, market_radar=market_radar)

        self.assertNotIn('market_radar_bonus', breakdown.multipliers)

    def test_market_radar_bonus_absent_when_offer_has_no_category(self):
        offer = self._make_offer(category=None)
        market_radar = {'category_scores': {'tecnologia_cotidiana_qa': 0.99}}

        breakdown = quality_score_breakdown(offer, market_radar=market_radar)

        self.assertNotIn('market_radar_bonus', breakdown.multipliers)

    def test_market_radar_disabled_result_shape_has_no_effect(self):
        offer = self._make_offer()
        # Formato devolvido por RadarMercadoResult(enabled=False).as_dict().
        disabled_radar = {
            'enabled': False,
            'collected_at': timezone.now().isoformat(),
            'category_scores': {},
            'product_scores': {},
            'sample_size': 0,
            'categories_covered': [],
            'limitations': 'SHOPEE_AFFILIATE_ENABLED=false',
        }

        breakdown = quality_score_breakdown(offer, market_radar=disabled_radar)

        self.assertNotIn('market_radar_bonus', breakdown.multipliers)
        self.assertAlmostEqual(breakdown.score, quality_score_breakdown(offer).score, places=3)

    # --- combinação ----------------------------------------------------------

    def test_both_bonuses_can_stack(self):
        offer = self._make_offer()
        observer_context = {'marketplace_counts': {'mercadolivre': 40}, 'editorial_label_counts': {}}
        market_radar = {'category_scores': {'tecnologia_cotidiana_qa': 0.9}}

        breakdown = quality_score_breakdown(offer, observer_context=observer_context, market_radar=market_radar)

        self.assertIn('observer_bonus', breakdown.multipliers)
        self.assertIn('market_radar_bonus', breakdown.multipliers)
        self.assertGreater(
            breakdown.score,
            quality_score_breakdown(offer, observer_context=observer_context).score,
        )
