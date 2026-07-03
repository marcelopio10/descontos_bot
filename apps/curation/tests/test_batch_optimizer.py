from django.test import SimpleTestCase

from apps.curation.services.batch_optimizer import (
    DEFAULT_TARGET_DISTRIBUTION,
    optimize_curation_batch,
)


class BatchOptimizerTests(SimpleTestCase):
    def _decision(self, offer_id, marketplace_code, score, *, classification='approved', risk_flags=None, title=None):
        return {
            'offer_id': offer_id,
            'marketplace_code': marketplace_code,
            'classification': classification,
            'selected_for_batch': False,
            'batch_position': None,
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

    def test_batch_of_20_respects_40_30_30_when_stock_exists(self):
        decisions = []
        offer_id = 1
        for marketplace in ('mercadolivre', 'amazon', 'shopee'):
            for index in range(10):
                decisions.append(self._decision(offer_id, marketplace, 100 - index))
                offer_id += 1

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual(result.actual_distribution, {'mercadolivre': 8, 'amazon': 6, 'shopee': 6})
        self.assertEqual(len(result.selected), 20)
        self.assertEqual([item['batch_position'] for item in result.selected], list(range(1, 21)))
        self.assertEqual(len({item['batch_position'] for item in result.selected}), 20)

    def test_redistributes_missing_marketplace_without_selecting_rejected_offers(self):
        decisions = []
        for index in range(8):
            decisions.append(self._decision(index + 1, 'mercadolivre', 90 - index))
        for index in range(8):
            decisions.append(self._decision(index + 20, 'amazon', 85 - index))
        for index in range(8):
            decisions.append(self._decision(index + 40, 'shopee', 99 - index, classification='rejected'))

        result = optimize_curation_batch(decisions, batch_size=20)

        self.assertEqual(len(result.selected), 16)
        self.assertEqual(result.actual_distribution, {'mercadolivre': 8, 'amazon': 8})
        self.assertNotIn('shopee', result.actual_distribution)
        self.assertTrue(all(item['classification'] == 'approved' for item in result.selected))

    def test_improper_and_safety_risk_never_enter_batch(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100),
            self._decision(2, 'amazon', 99, classification='improper'),
            self._decision(3, 'shopee', 98, risk_flags=['weapon']),
            self._decision(4, 'amazon', 97, risk_flags=['adult_content']),
            self._decision(5, 'shopee', 96, risk_flags=['obscene']),
        ]

        result = optimize_curation_batch(decisions, batch_size=5)

        self.assertEqual([item['offer_id'] for item in result.selected], [1])
        self.assertEqual(result.rejected_count, 4)

    def test_blocked_editorial_themes_are_detected_in_text_and_blacklist_actions(self):
        decisions = [
            self._decision(1, 'mercadolivre', 100, title='Cafeteira elétrica inox'),
            self._decision(2, 'amazon', 99, title='Walkie Talkie rádio comunicador potente'),
            {
                **self._decision(3, 'shopee', 98, title='Oferta comum'),
                'blacklist_actions': [{'term': 'arma de brinquedo'}],
            },
        ]

        result = optimize_curation_batch(decisions, batch_size=3)

        self.assertEqual([item['offer_id'] for item in result.selected], [1])
        self.assertEqual(result.rejected_count, 2)

    def test_orders_each_marketplace_by_ai_score_then_global_position(self):
        decisions = [
            self._decision(1, 'mercadolivre', 70),
            self._decision(2, 'mercadolivre', 95),
            self._decision(3, 'amazon', 80),
            self._decision(4, 'amazon', 99),
            self._decision(5, 'shopee', 81),
            self._decision(6, 'shopee', 82),
        ]

        result = optimize_curation_batch(decisions, batch_size=6)

        self.assertEqual([item['offer_id'] for item in result.selected], [4, 2, 6, 5, 3, 1])
        self.assertEqual(result.target_distribution, DEFAULT_TARGET_DISTRIBUTION)
