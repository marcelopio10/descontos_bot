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

# Termos de segurança não podem ser removidos pelo painel. Eles protegem todos
# os canais contra produtos adultos/obscenos e suplementos sexuais.
SAFETY_BLACKLIST_TERMS: tuple[str, ...] = (
    'super cavalo',
    'torofila',
    'aumenta super',
    'estimulante sexual',
    'desempenho sexual',
    'potencia sexual',
    'impotencia sexual',
    'libido',
    'erecao',
    'penis',
    'peniano',
    'aumentador peniano',
    'sexy shop',
    'vibrador',
    'masturbador',
    'massageador intimo',
    'lubrificante intimo',
)


def get_blacklist_terms() -> tuple[str, ...]:
    raw = get_json_setting(BLACKLIST_SETTING_KEY, list(DEFAULT_BLACKLIST_TERMS))
    if not isinstance(raw, (list, tuple)):
        raw = DEFAULT_BLACKLIST_TERMS

    return _normalize_terms((*raw, *SAFETY_BLACKLIST_TERMS))


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


def filter_blacklisted_offers(
    offers: list[Offer],
    terms: tuple[str, ...] | None = None,
) -> list[Offer]:
    terms = terms if terms is not None else get_blacklist_terms()
    return [offer for offer in offers if not is_blacklisted(offer, terms)]


def _normalize_terms(terms: tuple[object, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for term in terms:
        value = _strip_accents(str(term)).strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _term_matches(term: str, haystack: str) -> bool:
    pattern = r'\b' + re.escape(term) + r'\b'
    return re.search(pattern, haystack) is not None
