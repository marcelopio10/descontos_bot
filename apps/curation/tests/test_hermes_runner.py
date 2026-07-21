import json
import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.curation.services.hermes_runner import (
    FakeHermesRunner,
    HermesProfileRunner,
    HermesRunnerError,
    sanitize_ai_text,
    sanitize_hermes_payload,
)


class FakeHermesRunnerTests(SimpleTestCase):
    def test_fake_runner_selects_top_n_by_score_and_returns_valid_shape(self):
        runner = FakeHermesRunner()
        payload = {
            'schema_version': '1.0',
            'run': {'batch_size': 1},
            'offers': [
                {'offer_id': 1, 'marketplace_code': 'mercadolivre', 'title': 'Tênis Adidas', 'baseline': {'score': 90}},
                {'offer_id': 2, 'marketplace_code': 'amazon', 'title': 'Cafeteira', 'baseline': {'score': 80}},
            ],
        }

        output = runner.run(payload)

        self.assertEqual(output['schema_version'], '1.0')
        self.assertEqual(len(output['decisions']), 2)
        self.assertEqual(output['actual_distribution'], {})
        # offer_id=1 has higher score → selected
        d1 = next(d for d in output['decisions'] if d['offer_id'] == 1)
        d2 = next(d for d in output['decisions'] if d['offer_id'] == 2)
        self.assertTrue(d1['selected_for_batch'])
        self.assertEqual(d1['batch_position'], 1)
        self.assertFalse(d2['selected_for_batch'])
        self.assertIsNone(d2['batch_position'])
        self.assertEqual(d1['classification'], 'approved')
        self.assertIn('rewritten_caption_whatsapp', d1)

    def test_fake_runner_selects_all_when_batch_size_not_specified(self):
        runner = FakeHermesRunner()
        payload = {
            'schema_version': '1.0',
            'offers': [
                {'offer_id': 1, 'marketplace_code': 'mercadolivre', 'title': 'Tênis Adidas', 'baseline': {'score': 90}},
                {'offer_id': 2, 'marketplace_code': 'amazon', 'title': 'Cafeteira', 'baseline': {'score': 80}},
            ],
        }

        output = runner.run(payload)

        self.assertEqual(len(output['decisions']), 2)
        self.assertTrue(all(d['selected_for_batch'] for d in output['decisions']))

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
        self.assertEqual(command[:5], ['hermes', 'chat', '-Q', '--profile', 'descontos-bot'])
        query_index = command.index('-q')
        prompt = command[query_index + 1]
        # Sem override de modelo, nenhuma flag -m/--provider é injetada.
        self.assertNotIn('-m', command)
        self.assertNotIn('--provider', command)
        self.assertIn('JSON puro', prompt)
        self.assertIn('skill humanizer', prompt)
        self.assertIn('Não use fórmulas repetidas', prompt)
        self.assertIn('Evite repetir título, preço', prompt)
        self.assertIn('40% Mercado Livre, 30% Amazon e 30% Shopee', prompt)
        self.assertIn('low_priority_book', prompt)
        self.assertIn('livros têm baixa conversão', prompt)
        self.assertIn('"offer_id": 101', prompt)
        # profile is passed via --profile CLI flag
        self.assertIn('--profile', command)
        self.assertIn('descontos-bot', command)

    def test_profile_runner_injects_model_and_provider_override_keeping_profile(self):
        completed = subprocess.CompletedProcess(
            args=['hermes'],
            returncode=0,
            stdout='{"schema_version": "1.0", "decisions": [], "actual_distribution": {}}',
            stderr='',
        )

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed) as run:
            HermesProfileRunner(
                profile_name='descontos-bot',
                model_override='glm-5.2',
                provider_override='zai',
            ).run({'offers': []})

        command = run.call_args.args[0]
        # Profile permanece o mesmo; só o modelo/provider são sobrescritos.
        self.assertEqual(command[:5], ['hermes', 'chat', '-Q', '--profile', 'descontos-bot'])
        self.assertIn('-m', command)
        self.assertEqual(command[command.index('-m') + 1], 'glm-5.2')
        self.assertIn('--provider', command)
        self.assertEqual(command[command.index('--provider') + 1], 'zai')
        # A flag -m vem antes do prompt (-q é o último par).
        self.assertLess(command.index('-m'), command.index('-q'))

    def test_profile_runner_raises_on_nonzero_exit(self):
        completed = subprocess.CompletedProcess(args=['hermes'], returncode=2, stdout='', stderr='boom')

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
            with self.assertRaisesRegex(HermesRunnerError, 'Hermes CLI falhou'):
                HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})

    def test_profile_runner_raises_actionable_message_on_session_auth_error(self):
        for detail in ('session expired', 'auth token invalid', 'please login again', 'session not found'):
            completed = subprocess.CompletedProcess(args=['hermes'], returncode=1, stdout='', stderr=detail)

            with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
                with self.assertRaises(HermesRunnerError) as ctx:
                    HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})

            msg = str(ctx.exception)
            self.assertIn('sessão/autenticação inválida', msg)
            self.assertIn('descontos-bot', msg)
            self.assertIn('renove a autenticação', msg)

    def test_profile_runner_raises_when_output_has_no_json(self):
        completed = subprocess.CompletedProcess(args=['hermes'], returncode=0, stdout='sem json', stderr='')

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
            with self.assertRaisesRegex(HermesRunnerError, 'JSON'):
                HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})

    def test_profile_runner_sanitizes_leaked_reasoning_from_decisions(self):
        raw_output = {
            'schema_version': '1.0',
            'decisions': [
                {
                    'offer_id': 101,
                    'rewritten_title': 'Fone',
                    'rewritten_caption_whatsapp': (
                        '<think>o usuário quer uma legenda persuasiva</think>'
                        'Fone bluetooth ótimo custo-benefício.'
                    ),
                    'rewritten_caption_telegram': 'Let me think about this... Fone confiável pra treino.',
                }
            ],
            'actual_distribution': {},
        }
        completed = subprocess.CompletedProcess(
            args=['hermes'], returncode=0, stdout=json.dumps(raw_output), stderr='',
        )

        with patch('apps.curation.services.hermes_runner.subprocess.run', return_value=completed):
            output = HermesProfileRunner(profile_name='descontos-bot').run({'offers': []})

        decision = output['decisions'][0]
        self.assertEqual(decision['rewritten_caption_whatsapp'], 'Fone bluetooth ótimo custo-benefício.')
        self.assertEqual(decision['rewritten_caption_telegram'], 'Fone confiável pra treino.')
        self.assertNotIn('<think>', decision['rewritten_caption_whatsapp'])
        self.assertNotIn('Let me think', decision['rewritten_caption_telegram'])


class SanitizeAiTextTests(SimpleTestCase):
    """Tarefa 5.3 (achado P9): sanitização anti-vazamento de raciocínio da IA.

    Cobre tags <think>/<reasoning> (fechadas e não fechadas), prefixos de
    monólogo tipo "Let me think..."/"Okay, thinking about this...", cercas de
    código markdown perdidas, e garante que texto legítimo não é mutilado.
    """

    def test_removes_closed_think_block(self):
        raw = '<think>O usuário quer uma legenda persuasiva sobre o desconto.</think>Tênis confortável pra treino, preço bom.'
        self.assertEqual(sanitize_ai_text(raw), 'Tênis confortável pra treino, preço bom.')

    def test_removes_think_block_in_the_middle_of_the_text(self):
        raw = 'Boa pedida <think>hmm, será que soa natural?</think> pra quem treina de manhã.'
        self.assertEqual(sanitize_ai_text(raw), 'Boa pedida pra quem treina de manhã.')

    def test_removes_reasoning_and_thinking_tag_variants_case_insensitively(self):
        self.assertEqual(
            sanitize_ai_text('<REASONING>pensando no público-alvo</REASONING> Boa pedida pra presentear.'),
            'Boa pedida pra presentear.',
        )
        self.assertEqual(
            sanitize_ai_text('<Thinking>nota interna</Thinking> Preço baixo raro de ver.'),
            'Preço baixo raro de ver.',
        )

    def test_unclosed_think_tag_discards_everything_after_it(self):
        raw = '<think>Preciso considerar o tom e evitar clichês, ainda estou elaborando a frase ideal'
        self.assertEqual(sanitize_ai_text(raw), '')

    def test_removes_let_me_think_prefix_with_ellipsis(self):
        raw = 'Let me think about this... Fone bluetooth ótimo custo-benefício.'
        self.assertEqual(sanitize_ai_text(raw), 'Fone bluetooth ótimo custo-benefício.')

    def test_removes_okay_thinking_prefix_without_swallowing_the_real_caption(self):
        raw = 'Okay, thinking about this, aqui vai a legenda boa pro produto.'
        self.assertEqual(sanitize_ai_text(raw), 'aqui vai a legenda boa pro produto.')

    def test_removes_chained_reasoning_prefixes(self):
        raw = "Let's think. Okay, let me consider the audience. Camiseta básica com bom custo-benefício."
        self.assertEqual(sanitize_ai_text(raw), 'Camiseta básica com bom custo-benefício.')

    def test_removes_stray_code_fence_but_keeps_inner_text(self):
        raw = '```\nCafeteira elétrica compacta, ótima pra cozinha pequena.\n```'
        self.assertEqual(sanitize_ai_text(raw), 'Cafeteira elétrica compacta, ótima pra cozinha pequena.')

    def test_removes_json_language_tagged_code_fence(self):
        raw = '```json\nLiquidificador potente por um preço justo.\n```'
        self.assertEqual(sanitize_ai_text(raw), 'Liquidificador potente por um preço justo.')

    def test_does_not_treat_word_glued_to_backticks_as_a_language_tag(self):
        raw = '```oferta``` really boa pro dia a dia.'
        self.assertEqual(sanitize_ai_text(raw), 'oferta really boa pro dia a dia.')

    def test_does_not_mangle_a_normal_caption_without_any_leak(self):
        raw = 'Sabão Omo 5 litros por preço bom. Ótimo pra abastecer a lavanderia.'
        self.assertEqual(sanitize_ai_text(raw), raw)

    def test_does_not_strip_generic_words_that_merely_resemble_triggers(self):
        raw = 'Ok pessoal, esse tênis tá com preço incrível hoje.'
        self.assertEqual(sanitize_ai_text(raw), raw)

    def test_none_and_empty_input_return_empty_string(self):
        self.assertEqual(sanitize_ai_text(None), '')
        self.assertEqual(sanitize_ai_text(''), '')

    def test_collapses_internal_whitespace_left_behind_by_removed_blocks(self):
        raw = '<think>nota</think>   Camiseta   básica   confortável.'
        self.assertEqual(sanitize_ai_text(raw), 'Camiseta básica confortável.')


class SanitizeHermesPayloadTests(SimpleTestCase):
    def test_sanitizes_all_rewritten_fields_across_decisions(self):
        payload = {
            'decisions': [
                {
                    'offer_id': 1,
                    'rewritten_title': '<think>nota</think>Fone Bluetooth',
                    'rewritten_caption_whatsapp': 'Let me think... Preço bom pro fone.',
                    'rewritten_caption_telegram': 'Okay, thinking about this, preço bom pro fone também.',
                },
                {
                    'offer_id': 2,
                    'rewritten_title': 'Cafeteira',
                    'rewritten_caption_whatsapp': 'Ótima pra cozinha pequena.',
                    'rewritten_caption_telegram': 'Boa pra quem mora sozinho.',
                },
            ],
        }

        sanitized = sanitize_hermes_payload(payload)

        self.assertEqual(sanitized['decisions'][0]['rewritten_title'], 'Fone Bluetooth')
        self.assertEqual(sanitized['decisions'][0]['rewritten_caption_whatsapp'], 'Preço bom pro fone.')
        self.assertEqual(sanitized['decisions'][0]['rewritten_caption_telegram'], 'preço bom pro fone também.')
        # Já limpo — não deve mudar.
        self.assertEqual(sanitized['decisions'][1]['rewritten_title'], 'Cafeteira')
        self.assertEqual(sanitized['decisions'][1]['rewritten_caption_whatsapp'], 'Ótima pra cozinha pequena.')

    def test_ignores_missing_or_non_string_fields_without_raising(self):
        payload = {'decisions': [{'offer_id': 1}, {'offer_id': 2, 'rewritten_title': None}, 'not-a-dict']}
        sanitized = sanitize_hermes_payload(payload)
        self.assertEqual(sanitized, payload)

    def test_returns_payload_unchanged_when_there_is_no_decisions_key(self):
        payload = {'schema_version': '1.0', 'actual_distribution': {}}
        self.assertEqual(sanitize_hermes_payload(payload), payload)
