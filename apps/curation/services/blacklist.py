import re
import unicodedata

from django.db.models import Q, QuerySet

from apps.curation.services.settings import get_json_setting
from apps.offers.models import Offer


BLACKLIST_SETTING_KEY = 'blacklist_terms'

DEFAULT_BLACKLIST_TERMS: tuple[str, ...] = (
    'usado',
    'reembalado',
    'avariado',
    'seminovo',
    'sem garantia',
    'produto indisponivel',
    'recondicionado',
    'danificado',
    'com defeito',
    'open box',
    'mostruario',
)


def get_blacklist_terms() -> tuple[str, ...]:
    raw = get_json_setting(BLACKLIST_SETTING_KEY, list(DEFAULT_BLACKLIST_TERMS))
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_BLACKLIST_TERMS

    terms = tuple(
        _strip_accents(str(term)).strip().lower()
        for term in raw
        if str(term).strip()
    )
    return terms or DEFAULT_BLACKLIST_TERMS


def is_blacklisted(offer: Offer, terms: tuple[str, ...] | None = None) -> bool:
    terms = terms if terms is not None else get_blacklist_terms()
    if not terms:
        return False

    haystack = _strip_accents(
        f'{offer.title or ""} {offer.normalized_title or ""}',
    ).lower()
    return any(_term_matches(term, haystack) for term in terms)


def apply_blacklist_exclusion(
    queryset: QuerySet[Offer],
    terms: tuple[str, ...] | None = None,
) -> QuerySet[Offer]:
    terms = terms if terms is not None else get_blacklist_terms()
    if not terms:
        return queryset

    exclusion = Q()
    for term in terms:
        exclusion |= Q(title__icontains=term) | Q(normalized_title__icontains=term)
    return queryset.exclude(exclusion)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _term_matches(term: str, haystack: str) -> bool:
    pattern = r'\b' + re.escape(term) + r'\b'
    return re.search(pattern, haystack) is not None
