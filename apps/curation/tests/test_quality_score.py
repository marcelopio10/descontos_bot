from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.quality_score import quality_score, quality_score_breakdown
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer, PriceHistoryEntry


class HistorySuspectPriceTests(TestCase):
    """Sprint 5 / achado F, H5: penalidade de desconto falso usando histórico real."""

    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )
        self.now = timezone.now()

    def _make_offer(self, *, original_price, current_price, discount_pct, external_id) -> Offer:
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=external_id,
            title=f'Produto {external_id}',
            normalized_title=f'produto {external_id}',
            offer_hash=f'hash-{external_id}',
            slug=f'produto-{external_id}',
            current_price=current_price,
            original_price=original_price,
            discount_pct=discount_pct,
            product_url=f'https://example.com/{external_id}',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=self.now,
            last_seen_at=self.now,
            price_collected_at=self.now,
        )

    def _add_history(self, offer: Offer, prices: list[str]) -> None:
        for index, price in enumerate(prices):
            PriceHistoryEntry.objects.create(
                offer=offer,
                price=Decimal(price),
                collected_at=self.now - timezone.timedelta(days=len(prices) - index),
            )

    def test_no_history_does_not_trigger_history_penalty(self):
        offer = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='no-history',
        )

        breakdown = quality_score_breakdown(offer)

        self.assertNotIn('history_suspect_price', breakdown.penalties)

    def test_single_history_entry_is_insufficient_data_and_does_not_penalize(self):
        offer = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='one-entry',
        )
        self._add_history(offer, ['59.90'])

        breakdown = quality_score_breakdown(offer)

        self.assertNotIn('history_suspect_price', breakdown.penalties)

    def test_original_price_far_above_historical_minimum_is_penalized(self):
        offer = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='inflated',
        )
        # A oferta nunca foi observada de fato acima de 65 — "De R$199,90" é
        # bem mais alto que qualquer preço real já coletado.
        self._add_history(offer, ['59.90', '65.00'])

        breakdown = quality_score_breakdown(offer)

        self.assertIn('history_suspect_price', breakdown.penalties)
        self.assertLess(breakdown.penalties['history_suspect_price'], 1.0)

    def test_original_price_consistent_with_historical_minimum_is_not_penalized(self):
        offer = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='consistent',
        )
        # Histórico mostra que a oferta de fato girava perto do "De R$" antes
        # de cair para o preço atual — desconto real, não inflado.
        self._add_history(offer, ['190.00', '199.90'])

        breakdown = quality_score_breakdown(offer)

        self.assertNotIn('history_suspect_price', breakdown.penalties)

    def test_same_nominal_discount_scores_lower_when_history_shows_inflated_original(self):
        inflated = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='cmp-inflated',
        )
        self._add_history(inflated, ['59.90', '65.00'])

        consistent = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='cmp-consistent',
        )
        self._add_history(consistent, ['190.00', '199.90'])

        self.assertLess(quality_score(inflated), quality_score(consistent))

    def test_history_note_never_includes_the_raw_historical_price_value(self):
        """RESTR-05: a nota é só para uso interno/IA — nunca cita o valor histórico."""
        offer = self._make_offer(
            original_price=Decimal('199.90'),
            current_price=Decimal('59.90'),
            discount_pct=Decimal('70.00'),
            external_id='note-check',
        )
        self._add_history(offer, ['59.90', '65.00'])

        breakdown = quality_score_breakdown(offer)
        notes_text = ' '.join(breakdown.notes)

        self.assertNotIn('59.9', notes_text)
        self.assertNotIn('65.0', notes_text)
        self.assertNotIn('199.9', notes_text)
