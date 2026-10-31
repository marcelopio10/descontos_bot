import pathlib
import unittest


class ExperimentIsolationTests(unittest.TestCase):
    def test_experiments_are_not_imported_by_production_modules(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        production_files = list((root / 'apps').rglob('*.py'))
        joined = '\n'.join(path.read_text(encoding='utf-8') for path in production_files)
        self.assertNotIn('experiments.mercadolivre_affiliate', joined)

    def test_candidate_registry_contains_no_secret_material(self):
        content = (pathlib.Path(__file__).parent / 'candidates.json').read_text(encoding='utf-8')
        for marker in ('ML_COOKIE', 'ML_CSRF_TOKEN', 'access_token', 'client_secret'):
            self.assertNotIn(marker, content)
