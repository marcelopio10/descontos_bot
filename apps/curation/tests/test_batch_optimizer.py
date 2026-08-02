from django.test import SimpleTestCase

from apps.curation.services.batch_optimizer import (
    DEFAULT_TARGET_DISTRIBUTION,
    optimize_curation_batch,
)


class BatchOptimizerTests(SimpleTestCase):
    def _decision(
        self,
        offer_id,
        marketplace_code,
        score,
        *,
        selected=True,
        position=None,
        classification='approved',
        risk_flags=None,
        title=None,
    ):
        return {
            'offer_id': offer_id,
            'marketplace_code': marketplace_code,
            'classification': classification,
            'selected_for_batch': selected,
            'batch_position': position,
            'conversion_score': score,
            'relevance_score': score,
            'discount_quality_score': score,
            'audience_fit_score': score,
            'reason': 'ok',
            'rewritten_title': title or f'Oferta {offer_id}',
            'rewritten_caption_whatsapp': f'Caption whatsapp {offer_id}',
            'rewritten_caption_telegram': f'Caption telegram {offer_id}',
            'image_required': False,
            'image_decision': 'skip',
            'blacklist_actions': [],
            'risk_flags': risk_flags or [],
        }

    def test_only_ai_selected_offers_enter_batch(self):
        decisions = [
            self._decision(1, 'mercadolivre', 70, selected=False),
            self._decision(2, 'amazon', 95, selected=True, position=1),
            self._decision(3, 'shopee', 99, selected=False),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual([item['offer_id'] for item in result.selected], [2, 3, 1])
        self.assertEqual(result.actual_distribution, {'amazon': 1, 'shopee': 1, 'mercadolivre': 1})
        self.assertEqual(result.rejected_count, 2)

    def test_preserves_ai_order_then_normalizes_positions(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, selected=True, position=3),
            self._decision(2, 'amazon', 80, selected=True, position=1),
            self._decision(3, 'shopee', 90, selected=True, position=2),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual([item['offer_id'] for item in result.selected], [2, 3, 1])
        self.assertEqual([item['batch_position'] for item in result.selected], [1, 2, 3])
        self.assertEqual(result.actual_distribution, {'amazon': 1, 'shopee': 1, 'mercadolivre': 1})

    def test_caps_ai_selected_batch_without_filling_with_unselected_offers(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, selected=True, position=1),
            self._decision(2, 'amazon', 99, selected=True, position=2),
            self._decision(3, 'shopee', 98, selected=True, position=3),
            self._decision(4, 'mercadolivre', 97, selected=False),
        ]

        result = optimize_curation_batch(decisions, batch_size=2)

        self.assertEqual([item['offer_id'] for item in result.selected], [1, 2])
        self.assertEqual(result.actual_distribution, {'mercadolivre': 1, 'amazon': 1})
        self.assertEqual(result.rejected_count, 1)

    def test_improper_and_safety_risk_never_enter_batch_even_when_ai_selected(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, selected=True, position=1),
            self._decision(2, 'amazon', 99, selected=True, position=2, classification='improper'),
            self._decision(3, 'shopee', 98, selected=True, position=3, risk_flags=['weapon']),
            self._decision(4, 'amazon', 97, selected=True, position=4, risk_flags=['adult_content']),
            self._decision(5, 'shopee', 96, selected=True, position=5, risk_flags=['obscene']),
        ]

        result = optimize_curation_batch(decisions, batch_size=5)

        self.assertEqual([item['offer_id'] for item in result.selected], [1])
        self.assertEqual(result.rejected_count, 4)

    def test_blocked_editorial_themes_are_detected_in_text_and_blacklist_actions(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, selected=True, position=1, title='Cafeteira elétrica inox'),
            self._decision(2, 'amazon', 99, selected=True, position=2, title='Walkie Talkie rádio comunicador potente'),
            {
                **self._decision(3, 'shopee', 98, selected=True, position=3, title='Oferta comum'),
                'blacklist_actions': [{'term': 'arma de brinquedo'}],
            },
        ]

        result = optimize_curation_batch(decisions, batch_size=3)

        self.assertEqual([item['offer_id'] for item in result.selected], [1])
        self.assertEqual(result.rejected_count, 2)

    def test_target_distribution_remains_metadata_not_selection_logic(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, selected=True, position=1),
            self._decision(2, 'mercadolivre', 90, selected=True, position=2),
            self._decision(3, 'amazon', 99, selected=False),
            self._decision(4, 'shopee', 98, selected=False),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual(result.target_distribution, DEFAULT_TARGET_DISTRIBUTION)
        self.assertEqual(result.actual_distribution, {'mercadolivre': 2, 'amazon': 1, 'shopee': 1})
        self.assertEqual([item['offer_id'] for item in result.selected], [1, 2, 3, 4])


class CanonicalProductDedupTests(SimpleTestCase):
    """Sprint 5 / achado P8: só uma oferta por produto_canonico_id entra no lote."""

    def _decision(
        self,
        offer_id,
        marketplace_code,
        score,
        *,
        selected=True,
        position=None,
        classification='approved',
        risk_flags=None,
        produto_canonico_id='',
        current_price=None,
    ):
        decision = {
            'offer_id': offer_id,
            'marketplace_code': marketplace_code,
            'classification': classification,
            'selected_for_batch': selected,
            'batch_position': position,
            'conversion_score': score,
            'relevance_score': score,
            'discount_quality_score': score,
            'audience_fit_score': score,
            'reason': 'ok',
            'rewritten_title': f'Oferta {offer_id}',
            'rewritten_caption_whatsapp': f'Caption whatsapp {offer_id}',
            'rewritten_caption_telegram': f'Caption telegram {offer_id}',
            'image_required': False,
            'image_decision': 'skip',
            'blacklist_actions': [],
            'risk_flags': risk_flags or [],
            'produto_canonico_id': produto_canonico_id,
        }
        if current_price is not None:
            decision['current_price'] = current_price
        return decision

    def test_two_offers_same_asin_only_higher_score_enters_batch(self):
        decisions = [
            self._decision(1, 'amazon', 90, produto_canonico_id='amazon:B0SAME1234', current_price=99.90),
            self._decision(2, 'amazon', 70, produto_canonico_id='amazon:B0SAME1234', current_price=79.90),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual([item['offer_id'] for item in result.selected], [1])
        self.assertEqual(result.rejected_count, 1)
        self.assertFalse(result.rejected[0]['selected_for_batch'])

    def test_cheaper_offer_wins_price_tie_break_when_scores_are_equal(self):
        decisions = [
            self._decision(1, 'shopee', 80, produto_canonico_id='shopee:111222333', current_price=59.90),
            self._decision(2, 'shopee', 80, produto_canonico_id='shopee:111222333', current_price=49.90),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual([item['offer_id'] for item in result.selected], [2])

    def test_ai_selected_duplicate_wins_over_higher_score_unselected_duplicate(self):
        decisions = [
            self._decision(1, 'mercadolivre', 99, selected=False, produto_canonico_id='mercadolivre:MLB1'),
            self._decision(2, 'mercadolivre', 50, selected=True, position=1, produto_canonico_id='mercadolivre:MLB1'),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        # A dedup nunca pode derrubar o único candidato de fato aprovado pela
        # IA por causa de uma duplicata que a IA nem selecionou.
        self.assertEqual([item['offer_id'] for item in result.selected], [2])

    def test_ineligible_duplicate_does_not_block_its_eligible_sibling(self):
        decisions = [
            self._decision(1, 'amazon', 95, produto_canonico_id='amazon:B0X', classification='improper'),
            self._decision(2, 'amazon', 80, produto_canonico_id='amazon:B0X'),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual([item['offer_id'] for item in result.selected], [2])

    def test_empty_canonical_id_never_triggers_dedup(self):
        decisions = [
            self._decision(1, 'mercadolivre', 90, produto_canonico_id=''),
            self._decision(2, 'mercadolivre', 80, produto_canonico_id=''),
        ]

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual({item['offer_id'] for item in result.selected}, {1, 2})
