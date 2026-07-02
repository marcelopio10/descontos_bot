from __future__ import annotations

import json
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.curation.models import CurationBlacklistTerm, CurationDecision, CurationRun
from apps.curation.services.blacklist import BLACKLIST_SETTING_KEY, DEFAULT_BLACKLIST_TERMS, _strip_accents
from apps.offers.models import Offer
from apps.panel.models import Setting


@dataclass(frozen=True)
class BlacklistUpdateResult:
    term: CurationBlacklistTerm
    created: bool
    added_to_setting: bool


@dataclass(frozen=True)
class BlacklistRollbackResult:
    term: CurationBlacklistTerm
    removed_from_setting: bool


def add_curation_blacklist_term(
    *,
    term: str,
    source: str,
    offer: Offer | None = None,
    decision: CurationDecision | None = None,
    run: CurationRun | None = None,
) -> BlacklistUpdateResult:
    clean_term = _clean_display_term(term)
    normalized = normalize_blacklist_term(clean_term)
    if not normalized:
        raise ValueError('termo obrigatório')

    with transaction.atomic():
        setting_terms = _load_setting_terms_for_update()
        added_to_setting = _append_term(setting_terms, normalized)
        if added_to_setting:
            _save_setting_terms(setting_terms)

        existing = CurationBlacklistTerm.objects.filter(
            normalized_term=normalized,
            status=CurationBlacklistTerm.Status.ACTIVE,
        ).first()
        if existing:
            return BlacklistUpdateResult(term=existing, created=False, added_to_setting=added_to_setting)

        audit = CurationBlacklistTerm.objects.create(
            term=clean_term,
            normalized_term=normalized,
            source=source,
            offer=offer,
            decision=decision,
            run=run,
            status=CurationBlacklistTerm.Status.ACTIVE,
            added_to_setting_at=timezone.now(),
        )
        return BlacklistUpdateResult(term=audit, created=True, added_to_setting=added_to_setting)


def rollback_curation_blacklist_term(
    *,
    term: str | None = None,
    term_id: int | None = None,
    reason: str = '',
) -> BlacklistRollbackResult:
    if not term and term_id is None:
        raise ValueError('term ou term_id obrigatório')

    with transaction.atomic():
        audit = _find_active_term(term=term, term_id=term_id)
        setting_terms = _load_setting_terms_for_update()
        removed = _remove_term(setting_terms, audit.normalized_term)
        if removed:
            _save_setting_terms(setting_terms)

        audit.status = CurationBlacklistTerm.Status.ROLLED_BACK
        audit.rolled_back_at = timezone.now()
        audit.rollback_reason = reason
        audit.save(update_fields=['status', 'rolled_back_at', 'rollback_reason', 'updated_at'])
        return BlacklistRollbackResult(term=audit, removed_from_setting=removed)


def normalize_blacklist_term(term: str) -> str:
    return _strip_accents(str(term or '')).strip().lower()


def _clean_display_term(term: str) -> str:
    return ' '.join(str(term or '').strip().split())


def _load_setting_terms_for_update() -> list[str]:
    setting, _ = Setting.objects.select_for_update().get_or_create(
        key=BLACKLIST_SETTING_KEY,
        defaults={
            'value': json.dumps(list(DEFAULT_BLACKLIST_TERMS), ensure_ascii=False),
            'description': 'Termos dinâmicos de blacklist da curadoria.',
        },
    )
    try:
        raw = json.loads(setting.value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = list(DEFAULT_BLACKLIST_TERMS)
    if not isinstance(raw, list):
        raw = list(DEFAULT_BLACKLIST_TERMS)
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw:
        item = normalize_blacklist_term(str(value))
        if item and item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized


def _save_setting_terms(terms: list[str]) -> None:
    Setting.objects.update_or_create(
        key=BLACKLIST_SETTING_KEY,
        defaults={
            'value': json.dumps(terms, ensure_ascii=False, sort_keys=True),
            'description': 'Termos dinâmicos de blacklist da curadoria.',
        },
    )


def _append_term(terms: list[str], normalized: str) -> bool:
    if normalized in terms:
        return False
    terms.append(normalized)
    return True


def _remove_term(terms: list[str], normalized: str) -> bool:
    before = len(terms)
    terms[:] = [term for term in terms if normalize_blacklist_term(term) != normalized]
    return len(terms) != before


def _find_active_term(*, term: str | None, term_id: int | None) -> CurationBlacklistTerm:
    queryset = CurationBlacklistTerm.objects.select_for_update().filter(status=CurationBlacklistTerm.Status.ACTIVE)
    if term_id is not None:
        found = queryset.filter(id=term_id).first()
    else:
        found = queryset.filter(normalized_term=normalize_blacklist_term(term or '')).first()
    if not found:
        raise ValueError('termo ativo não encontrado')
    return found
