from django.test import SimpleTestCase

from apps.curation.services.ai_schema import validate_agent_input, validate_agent_output


class AISchemaTests(SimpleTestCase):
    def test_valid_agent_input_passes(self):
        payload = {
            'schema_version': '1.0',
            'run': {
                'run_id': 123,
                'mode': 'dry_run',
                'channel_code': 'whatsapp_main',
                'batch_size': 20,
                'target_distribution': {'mercadolivre': 0.4, 'amazon': 0.3, 'shopee': 0.3},
            },
            'editorial_policy': {'tone': 'honesto'},
            'baseline_rules': {'min_discount_percentage': 20},
            'observer_context': {},
            'offers': [
                {
                    'offer_id': 1,
                    'title': 'Produto bom',
                    'marketplace_code': 'mercadolivre',
                    'current_price': 99.9,
                    'discount_pct': 30,
                    'baseline': {'score': 80},
                }
            ],
        }

        result = validate_agent_input(payload)

        self.assertTrue(result.is_valid, result.errors)

    def test_invalid_agent_output_fails_for_improper_selected_offer(self):
        payload = {
            'schema_version': '1.0',
            'actual_distribution': {'mercadolivre': 1},
            'decisions': [
                {
                    'offer_id': 1,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'improper',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 90,
                    'relevance_score': 90,
                    'discount_quality_score': 90,
                    'audience_fit_score': 90,
                    'reason': 'errado',
                    'rewritten_title': 'Título',
                    'rewritten_caption_whatsapp': 'Caption',
                    'rewritten_caption_telegram': 'Caption',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            ],
        }

        result = validate_agent_output(payload, expected_offer_ids={1})

        self.assertFalse(result.is_valid)
        self.assertIn('imprópria não pode ser selecionada', '; '.join(result.errors))

    def test_invalid_agent_output_fails_for_selected_offer_without_caption(self):
        payload = {
            'schema_version': '1.0',
            'decisions': [
                {
                    'offer_id': 1,
                    'marketplace_code': 'amazon',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 90,
                    'relevance_score': 90,
                    'discount_quality_score': 90,
                    'audience_fit_score': 90,
                    'reason': 'ok',
                    'rewritten_title': 'Título',
                    'rewritten_caption_whatsapp': '',
                    'rewritten_caption_telegram': 'Caption',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            ],
        }

        result = validate_agent_output(payload)

        self.assertFalse(result.is_valid)
        self.assertIn('selecionada sem caption WhatsApp', '; '.join(result.errors))

    def test_invalid_agent_output_fails_for_duplicate_positions(self):
        def decision(offer_id):
            return {
                'offer_id': offer_id,
                'marketplace_code': 'shopee',
                'classification': 'approved',
                'selected_for_batch': True,
                'batch_position': 1,
                'conversion_score': 90,
                'relevance_score': 90,
                'discount_quality_score': 90,
                'audience_fit_score': 90,
                'reason': 'ok',
                'rewritten_title': 'Título',
                'rewritten_caption_whatsapp': 'Caption',
                'rewritten_caption_telegram': 'Caption',
                'image_required': False,
                'image_decision': 'skip',
                'blacklist_actions': [],
                'risk_flags': [],
            }

        result = validate_agent_output({'schema_version': '1.0', 'decisions': [decision(1), decision(2)]})

        self.assertFalse(result.is_valid)
        self.assertIn('duplicada', '; '.join(result.errors))
