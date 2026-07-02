import json
import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.curation.services.hermes_runner import FakeHermesRunner, HermesProfileRunner, HermesRunnerError


class FakeHermesRunnerTests(SimpleTestCase):
    def test_fake_runner_returns_valid_json_shape_for_every_offer(self):
        runner = FakeHermesRunner()
        payload = {
            'schema_version': '1.0',
            'offers': [
                {'offer_id': 1, 'marketplace_code': 'mercadolivre', 'title': 'Tênis Adidas', 'baseline': {'score': 90}},
                {'offer_id': 2, 'marketplace_code': 'amazon', 'title': 'Cafeteira', 'baseline': {'score': 80}},
            ],
        }

        output = runner.run(payload)

        self.assertEqual(output['schema_version'], '1.0')
        self.assertEqual(len(output['decisions']), 2)
        self.assertEqual(output['actual_distribution'], {})
        self.assertEqual(output['decisions'][0]['offer_id'], 1)
        self.assertEqual(output['decisions'][0]['classification'], 'approved')
        self.assertFalse(output['decisions'][0]['selected_for_batch'])
        self.assertIn('rewritten_caption_whatsapp', output['decisions'][0])

    def test_fake_runner_can_simulate_failure(self):
        runner = FakeHermesRunner(should_fail=True)

        with self.assertRaises(HermesRunnerError):
            runner.run({'offers': []})

    def test_fake_runner_can_return_forced_payload(self):
        forced_payload = {'schema_version': 'invalid', 'decisions': []}
        runner = FakeHermesRunner(forced_payload=forced_payload)

        self.assertIs(runner.run({'offers': []}), forced_payload)


class HermesProfileRunnerTests(SimpleTestCase):
    def test_profile_runner_calls_hermes_cli_and_extracts_json(self):
        payload = {'schema_version': '1.0', 'offers': [{'offer_id': 101, 'title': 'Fone'}]}
        expected = {
            'schema_version': '1.0',
            'decisions': [
                {
                    'offer_id': 101,
                    'marketplace_code': 'mercadolivre',
                    'classification': 'approved',
                    'selected_for_batch': True,
                    'batch_position': 1,
                    'conversion_score': 90,
                    'relevance_score': 90,
                    'discount_quality_score': 90,
                    'audience_fit_score': 90,
                    'reason': 'Boa oferta.',
                    'rewritten_title': 'Fone',
                    'rewritten_caption_whatsapp': 'Caption W',
                    'rewritten_caption_telegram': 'Caption T',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            ],
            'actual_distribution': {'mercadolivre': 1},
        }
        completed = subprocess.CompletedProcess(
            args=['hermes'],
            returncode=0,
            stdout=f'Warning: ignored\nsession_id: abc\n{json.dumps(expected)}\n',
            stderr='',
        )

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed) as run:
            output = HermesProfileRunner(profile_name='descontos-bot', timeout_seconds=12).run(payload)

        self.assertEqual(output, expected)
        command = run.call_args.args[0]
        self.assertEqual(command[:5], ['hermes', '-p', 'descontos-bot', 'chat', '-Q'])
        self.assertIn('-q', command)
        prompt = command[command.index('-q') + 1]
        self.assertIn('JSON puro', prompt)
        self.assertIn('"offer_id": 101', prompt)

    def test_profile_runner_raises_on_nonzero_exit(self):
        completed = subprocess.CompletedProcess(args=['hermes'], returncode=2, stdout='', stderr='boom')

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
            with self.assertRaisesRegex(HermesRunnerError, 'Hermes CLI falhou'):
                HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})

    def test_profile_runner_raises_when_output_has_no_json(self):
        completed = subprocess.CompletedProcess(args=['hermes'], returncode=0, stdout='sem json', stderr='')

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
            with self.assertRaisesRegex(HermesRunnerError, 'JSON'):
                HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})
