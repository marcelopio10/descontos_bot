from unittest.mock import patch

from django.test import SimpleTestCase

from apps.orchestration.management.commands.run_bot import _ai_curation_attempts


class AICurationAttemptsTests(SimpleTestCase):
    """Achado 2026-08-21: o fallback nunca pôde funcionar.

    `-m glm-5.2` era passado sem provider, então o Hermes tentava o modelo no
    provider ativo (Codex) e voltava `HTTP 400: The 'glm-5.2' model is not
    supported when using Codex with a ChatGPT account`. O GLM roda pela
    assinatura do opencode-go. Como o erro trazia a linha `session_id:` na
    saída, o classificador do runner ainda o rotulava como falha de
    autenticação — dois enganos empilhados sobre a mesma falha.
    """

    def test_primario_nao_forca_modelo_nem_provider(self):
        label, model, provider = _ai_curation_attempts()[0]

        self.assertIn('primário', label)
        self.assertIsNone(model)
        self.assertIsNone(provider)

    def test_fallback_padrao_leva_o_provider_do_glm(self):
        with patch.dict('os.environ', {'AI_CURATION_FALLBACK_MODELS': ''}):
            attempts = _ai_curation_attempts()

        self.assertEqual(attempts[1][1:], ('glm-5.2', 'opencode-go'))
        self.assertIn('opencode-go', attempts[1][0])

    def test_env_override_aceita_modelo_arroba_provider(self):
        with patch.dict('os.environ', {'AI_CURATION_FALLBACK_MODELS': 'glm-4.6@opencode-go, outro-modelo'}):
            attempts = _ai_curation_attempts()

        self.assertEqual(attempts[1][1:], ('glm-4.6', 'opencode-go'))
        # Sem `@provider`, herda o provider do profile.
        self.assertEqual(attempts[2][1:], ('outro-modelo', None))
