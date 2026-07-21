import re
from pathlib import Path

from django.test import SimpleTestCase


# Sprint 5 / Tarefa 5.2 (RESTR-05): o histórico de preço é exclusivamente
# interno (só pontua a curadoria). Nenhum valor histórico pode ser citado nas
# mensagens publicadas. Este teste espelha o grep de compliance do plano de
# refatoração e falha caso alguém (de boa fé) introduza esse vazamento nos
# construtores de mensagem no futuro.
FORBIDDEN_PATTERNS = [
    re.compile(r'menor pre[çc]o', re.IGNORECASE),
    re.compile(r'era R\$', re.IGNORECASE),
    re.compile(r'pre[çc]o hist[óo]rico', re.IGNORECASE),
    re.compile(r'hist[óo]rico de pre[çc]o', re.IGNORECASE),
]

MESSAGE_BUILDER_FILES = [
    Path('apps/curation/services/message_builder.py'),
    Path('apps/curation/services/telegram_message_builder.py'),
]


class Restr05PriceHistoryComplianceTests(SimpleTestCase):
    def test_message_builders_never_mention_historical_price_language(self):
        repo_root = Path(__file__).resolve().parents[3]
        for relative_path in MESSAGE_BUILDER_FILES:
            path = repo_root / relative_path
            self.assertTrue(path.exists(), f'arquivo esperado não encontrado: {path}')
            content = path.read_text(encoding='utf-8')
            for pattern in FORBIDDEN_PATTERNS:
                match = pattern.search(content)
                self.assertIsNone(
                    match,
                    f'RESTR-05 violado: "{match.group(0) if match else pattern.pattern}" encontrado em {relative_path}',
                )
