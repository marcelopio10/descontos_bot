from django.test import SimpleTestCase

from apps.curation.services.hermes_runner import FakeHermesRunner, HermesRunnerError


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
