from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.curation.services.message_builder import (
    BADGE_VARIANTS,
    _build_badge,
    _fallback_agent_highlight,
    _select_badge_variant,
    _variant_index,
    build_message,
)
from apps.curation.services.telegram_message_builder import _build_badge as _telegram_build_badge
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class VariantIndexTests(SimpleTestCase):
    """`_variant_index` é a base de toda a variação determinística (highlight e
    badge) usada na Tarefa 5.3. Não testamos "é aleatório" (não é) — testamos que o
    mesmo seed sempre reproduz o mesmo índice e que seeds diferentes tendem a variar.
    """

    def test_same_seed_always_returns_same_index(self):
        self.assertEqual(_variant_index(101, 4), _variant_index(101, 4))
        self.assertEqual(_variant_index(101, 4), _variant_index(101, 4))

    def test_different_seeds_vary_the_index(self):
        indices = {_variant_index(seed, 4) for seed in range(0, 20)}
        self.assertGreater(len(indices), 1)

    def test_none_seed_and_zero_count_do_not_raise(self):
        self.assertEqual(_variant_index(None, 4), 0)
        self.assertEqual(_variant_index(5, 0), 0)


class FallbackHighlightVariationTests(SimpleTestCase):
    """`_fallback_agent_highlight` (achado P9): antes retornava sempre a MESMA frase
    fixa por categoria. Testes cobrem reprodutibilidade (mesma oferta -> mesma frase)
    e variação real (ofertas diferentes -> frases diferentes), não aleatoriedade.
    """

    @staticmethod
    def _offer(offer_id: int, title: str) -> Offer:
        return Offer(id=offer_id, title=title)

    def test_same_offer_id_always_returns_the_same_phrase(self):
        offer = self._offer(42, 'Camiseta Masculina Slim Fit')
        first = _fallback_agent_highlight(offer)
        second = _fallback_agent_highlight(offer)
        third = _fallback_agent_highlight(offer)
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_different_offer_ids_can_produce_different_phrases_in_same_category(self):
        title = 'Camiseta Masculina Slim Fit'
        phrases = {_fallback_agent_highlight(self._offer(offer_id, title)) for offer_id in range(0, 4)}
        self.assertGreater(len(phrases), 1)

    def test_generic_category_also_varies_across_offers(self):
        title = 'Produto qualquer sem categoria reconhecida no titulo'
        phrases = {_fallback_agent_highlight(self._offer(offer_id, title)) for offer_id in range(0, 4)}
        self.assertGreater(len(phrases), 1)

    def test_all_variants_belong_to_the_declared_category_pool(self):
        title = 'Kit Creatina 300g'
        from apps.curation.services.message_builder import _FALLBACK_HIGHLIGHT_VARIANTS

        expected_pool = set(_FALLBACK_HIGHLIGHT_VARIANTS['suplemento'])
        for offer_id in range(0, 10):
            phrase = _fallback_agent_highlight(self._offer(offer_id, title))
            self.assertIn(phrase, expected_pool)

    def test_baby_category_phrases_stay_on_topic(self):
        for offer_id in range(0, 6):
            highlight = _fallback_agent_highlight(self._offer(offer_id, 'Mordedor para Bebe Sensorial'))
            self.assertTrue('bebê' in highlight.lower() or 'dentinhos' in highlight.lower())


class BadgeVariantTests(SimpleTestCase):
    """`_select_badge_variant`/`_build_badge` (achado P9): a faixa era um texto fixo
    por nível de desconto. Testamos determinismo por offer_id, variação entre ofertas
    e que os limites de faixa (30%/50%) continuam corretos.
    """

    def test_same_offer_id_and_discount_always_return_the_same_badge(self):
        first = _build_badge(10, 99)
        second = _build_badge(10, 99)
        self.assertEqual(first, second)

    def test_different_offer_ids_vary_the_badge_within_the_same_tier(self):
        badges = {_build_badge(10, offer_id) for offer_id in range(0, 4)}
        self.assertGreater(len(badges), 1)

    def test_tier_thresholds_are_preserved(self):
        self.assertIn(_select_badge_variant(50, 1), BADGE_VARIANTS['high'])
        self.assertIn(_select_badge_variant(75, 1), BADGE_VARIANTS['high'])
        self.assertIn(_select_badge_variant(30, 1), BADGE_VARIANTS['mid'])
        self.assertIn(_select_badge_variant(49, 1), BADGE_VARIANTS['mid'])
        self.assertIn(_select_badge_variant(29, 1), BADGE_VARIANTS['low'])
        self.assertIn(_select_badge_variant(0, 1), BADGE_VARIANTS['low'])

    def test_whatsapp_badge_uses_markdown_bold(self):
        badge = _build_badge(10, 3)
        self.assertIn('*', badge)
        self.assertNotIn('<b>', badge)


class BadgeCrossChannelConsistencyTests(SimpleTestCase):
    """Exigência explícita da Tarefa 5.3: WhatsApp e Telegram devem variar com o
    MESMO índice/critério (mesmo offer_id -> mesmo badge conceitual), só o formato
    de negrito muda (Markdown `*texto*` vs. HTML `<b>texto</b>`).
    """

    def test_same_offer_id_selects_the_same_conceptual_badge_on_both_channels(self):
        for offer_id in range(0, 6):
            for discount_pct in (5, 29, 30, 49, 50, 90):
                whatsapp_badge = _build_badge(discount_pct, offer_id)
                telegram_badge = _telegram_build_badge(discount_pct, offer_id)
                whatsapp_plain = whatsapp_badge.replace('*', '')
                telegram_plain = telegram_badge.replace('<b>', '').replace('</b>', '')
                self.assertEqual(
                    whatsapp_plain,
                    telegram_plain,
                    f'offer_id={offer_id} discount_pct={discount_pct}',
                )


class BuildMessageIntegrationTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Main',
            code='whatsapp_main',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
            is_enabled=True,
        )

    def _make_offer(self, offer_hash: str, discount_pct: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=offer_hash,
            title='Fone Bluetooth X',
            normalized_title='fone bluetooth x',
            offer_hash=offer_hash,
            slug=f'fone-{offer_hash}',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal(discount_pct),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_build_message_includes_a_badge_for_the_offer_discount_tier(self):
        offer = self._make_offer('badge-int-1', '18.00')
        message = build_message(offer, self.channel)
        lead, label, trail = _select_badge_variant(18, offer.id)
        self.assertIn(f'{lead} *{label}* {trail}', message)

    def test_same_offer_rendered_twice_yields_the_same_badge(self):
        offer = self._make_offer('badge-int-2', '40.00')
        first_message = build_message(offer, self.channel)
        second_message = build_message(offer, self.channel)
        self.assertEqual(first_message, second_message)
