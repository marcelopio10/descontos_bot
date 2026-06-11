import re
import unicodedata
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.curation.services.settings import get_json_setting


if TYPE_CHECKING:
    from apps.offers.models import Offer


SETTING_KEY = 'soft_penalty_terms'

# Termos que sinalizam contexto B2B/industrial sem serem hard blacklist.
# Cada termo carrega um fator multiplicativo aplicado ao score final.
DEFAULT_SOFT_PENALTIES: dict[str, float] = {
    'industrial': 0.40,
    'atacado': 0.50,
    'b2b': 0.40,
    'profissional para': 0.65,
    'uso profissional': 0.65,
    'kit com 100': 0.70,
    'kit com 50': 0.70,
    'pacote com 100': 0.70,
    'pacote com 50': 0.70,
    'caixa com 100': 0.70,
    'caixa com 50': 0.70,
    'fardo com': 0.70,
    'galao 5l': 0.75,
    'galao 20l': 0.65,
    'reposicao': 0.80,
}

# Regra de sinal fraco: oferta com pouco apelo combina desconto baixo + categoria fria + sem marca.
WEAK_SIGNAL_FACTOR = 0.75
WEAK_SIGNAL_DISCOUNT_THRESHOLD = Decimal('15')
WEAK_SIGNAL_COLD_CATEGORIES: frozenset[str] = frozenset(
    {'outros', 'automotivo', 'ferramentas', 'construcao', 'industrial'}
)


def evaluate_soft_penalties(offer: 'Offer') -> dict[str, float]:
    penalties: dict[str, float] = {}

    haystack = _normalize(
        f'{offer.title or ""} {offer.normalized_title or ""}',
    )

    for term, factor in _get_term_factors().items():
        if not term:
            continue
        normalized = _normalize(term)
        if not normalized:
            continue
        pattern = r'\b' + re.escape(normalized) + r'\b'
        if re.search(pattern, haystack):
            penalties[f'soft:{normalized}'] = factor

    if _is_weak_signal(offer):
        penalties['weak_signal'] = WEAK_SIGNAL_FACTOR

    return penalties


def _is_weak_signal(offer: 'Offer') -> bool:
    discount = offer.discount_pct or Decimal('0')
    if Decimal(discount) >= WEAK_SIGNAL_DISCOUNT_THRESHOLD:
        return False

    category_code = offer.category.code if getattr(offer, 'category_id', None) else None
    if category_code not in WEAK_SIGNAL_COLD_CATEGORIES and category_code is not None:
        return False

    if _has_strong_brand_marker(offer.title or ''):
        return False

    return True


def _has_strong_brand_marker(title: str) -> bool:
    # Reaproveita o dicionário do score sem importar para evitar ciclo.
    from apps.curation.services.quality_score import STRONG_BRANDS

    normalized = title.lower()
    return any(brand in normalized for brand in STRONG_BRANDS)


def _get_term_factors() -> dict[str, float]:
    raw = get_json_setting(SETTING_KEY, dict(DEFAULT_SOFT_PENALTIES))
    if not isinstance(raw, dict):
        return dict(DEFAULT_SOFT_PENALTIES)

    parsed: dict[str, float] = {}
    for term, factor in raw.items():
        try:
            value = float(factor)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value > 1:
            continue
        parsed[str(term)] = value
    return parsed or dict(DEFAULT_SOFT_PENALTIES)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text or '')
    stripped = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', stripped.lower()).strip()
