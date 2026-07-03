from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.curation.models import CurationBlacklistTerm
from apps.curation.services.blacklist import BLACKLIST_SETTING_KEY, SAFETY_BLACKLIST_TERMS, get_blacklist_terms
from apps.panel.models import Setting


class BlacklistUpdatesTests(TestCase):
    def test_add_term_updates_setting_and_creates_audit_record(self):
        from apps.curation.services.blacklist_updates import add_curation_blacklist_term

        result = add_curation_blacklist_term(
            term='  Produto Adulto  ',
            source=CurationBlacklistTerm.Source.AI_TEXT_MODERATION,
        )

        self.assertTrue(result.created)
        self.assertEqual(result.term.term, 'Produto Adulto')
        self.assertEqual(result.term.normalized_term, 'produto adulto')
        self.assertIsNotNone(result.term.added_to_setting_at)
        self.assertEqual(CurationBlacklistTerm.objects.count(), 1)
        self.assertIn('produto adulto', _setting_terms())
        self.assertIn('produto adulto', get_blacklist_terms())

    def test_duplicate_term_does_not_duplicate_setting_or_audit(self):
        from apps.curation.services.blacklist_updates import add_curation_blacklist_term

        first = add_curation_blacklist_term(term='Câmera Espiã', source=CurationBlacklistTerm.Source.AI_IMAGE_MODERATION)
        second = add_curation_blacklist_term(term='camera espia', source=CurationBlacklistTerm.Source.AI_TEXT_MODERATION)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.term.id, second.term.id)
        self.assertEqual(_setting_terms().count('camera espia'), 1)
        self.assertEqual(CurationBlacklistTerm.objects.filter(normalized_term='camera espia').count(), 1)

    def test_rollback_removes_automatic_term_and_updates_audit(self):
        from apps.curation.services.blacklist_updates import add_curation_blacklist_term, rollback_curation_blacklist_term

        added = add_curation_blacklist_term(term='Produto suspeito', source=CurationBlacklistTerm.Source.AI_TEXT_MODERATION)
        result = rollback_curation_blacklist_term(term='produto suspeito', reason='falso positivo')

        added.term.refresh_from_db()
        self.assertTrue(result.removed_from_setting)
        self.assertEqual(added.term.status, CurationBlacklistTerm.Status.ROLLED_BACK)
        self.assertEqual(added.term.rollback_reason, 'falso positivo')
        self.assertIsNotNone(added.term.rolled_back_at)
        self.assertNotIn('produto suspeito', _setting_terms())

    def test_rollback_command_removes_term(self):
        from apps.curation.services.blacklist_updates import add_curation_blacklist_term

        add_curation_blacklist_term(term='Termo automático', source=CurationBlacklistTerm.Source.AI_TEXT_MODERATION)

        out = StringIO()
        call_command(
            'rollback_curation_blacklist_term',
            '--term',
            'termo automatico',
            '--reason',
            'revisão humana',
            stdout=out,
        )

        self.assertIn('rolled_back=termo automatico', out.getvalue())
        self.assertNotIn('termo automatico', _setting_terms())

    def test_rollback_does_not_remove_hardcoded_safety_blacklist(self):
        from apps.curation.services.blacklist_updates import add_curation_blacklist_term, rollback_curation_blacklist_term

        safety_term = SAFETY_BLACKLIST_TERMS[0]
        add_curation_blacklist_term(term=safety_term, source=CurationBlacklistTerm.Source.AI_IMAGE_MODERATION)
        self.assertIn(safety_term, get_blacklist_terms())

        rollback_curation_blacklist_term(term=safety_term, reason='teste')

        self.assertNotIn(safety_term, _setting_terms())
        self.assertIn(safety_term, get_blacklist_terms())


def _setting_terms() -> list[str]:
    raw = Setting.objects.get(key=BLACKLIST_SETTING_KEY).value
    return json.loads(raw)
