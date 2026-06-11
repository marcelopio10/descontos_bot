from dataclasses import dataclass, field
from decimal import Decimal
from math import log10
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.curation.services.category_weights import (
    MAX_WEIGHT as CATEGORY_MAX_WEIGHT,
    resolve_category_weight,
)
from apps.curation.services.quality_filters import evaluate_soft_penalties
from apps.curation.services.settings import get_integer_setting
from apps.offers.services.freshness import resolve_max_age_hours


if TYPE_CHECKING:
    from apps.offers.models import Offer


FEATURE_FLAG_KEY = 'use_category_score'

# Pesos obrigatórios da Sprint 2: somam 100.
WEIGHT_DISCOUNT = 30.0
WEIGHT_POPULARITY = 30.0
WEIGHT_REVIEWS = 20.0
WEIGHT_PRICE = 10.0
WEIGHT_CATEGORY = 10.0

# Multiplicadores (gates fora dos 100 pontos).
MARKETPLACE_TRUST: dict[str, float] = {
    'amazon': 1.0,
    'mercado_livre': 0.95,
    'mercadolivre': 0.95,
}
DEFAULT_MARKETPLACE_TRUST = 0.85

EXTREME_DISCOUNT_THRESHOLD = Decimal('99')
SUSPECT_DISCOUNT_THRESHOLD = Decimal('85')
SUSPECT_PRICE_RATIO = Decimal('20')

PENALTY_NO_IMAGE = 0.7
PENALTY_SUSPECT_PRICE = 0.5
PENALTY_EXTREME_DISCOUNT = 0.0
PENALTY_TEST_CONTROLLED_CONFIDENCE = 0.85  # suplementos: viés do dono → fator de confiança

# Marcas reconhecidas — alimenta o critério de popularidade.
STRONG_BRANDS: frozenset[str] = frozenset(
    s.lower()
    for s in (
        'tramontina', 'brastemp', 'electrolux', 'oster', 'mondial', 'philco',
        'arno', 'philips walita', 'philips', 'britania', 'mallory', 'cadence',
        'samsung', 'lg', 'xiaomi', 'apple', 'motorola', 'jbl', 'sony', 'tcl',
        'logitech', 'nike', 'adidas', 'puma', 'mizuno', 'olympikus', 'fila',
        'insider', 'havaianas', 'lupo', 'kyly', 'fischer', 'cataventos',
        'mattel', 'hasbro', 'lego', 'fisher-price', 'estrela',
        'avon', 'natura', "o boticario", 'eudora', 'wella', 'taiff',
        'gama italy', 'mondial', 'oral-b', 'colgate', 'pampers', 'huggies',
        'nestle', 'piracanjuba', 'italac',
        'pedigree', 'whiskas', 'royal canin',
    )
)

# Etiqueta do scraper Amazon (source_label) que sinaliza bestseller.
BESTSELLER_LABELS: frozenset[str] = frozenset(
    s.lower()
    for s in ('mais vendidos', 'maiores altas', 'goldbox', 'ofertas do dia')
)


@dataclass(frozen=True)
class ScoreBreakdown:
    score: float
    components: dict[str, float]
    penalties: dict[str, float]
    multipliers: dict[str, float] = field(default_factory=dict)
    classification: str = ''
    decision: str = ''
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'score': round(self.score, 2),
            'components': {k: round(v, 2) for k, v in self.components.items()},
            'penalties': {k: round(v, 4) for k, v in self.penalties.items()},
            'multipliers': {k: round(v, 4) for k, v in self.multipliers.items()},
            'classification': self.classification,
            'decision': self.decision,
            'notes': list(self.notes),
        }


def quality_score(offer: 'Offer') -> float:
    return quality_score_breakdown(offer).score


def quality_score_breakdown(offer: 'Offer') -> ScoreBreakdown:
    if _category_scoring_enabled():
        return _category_aware_breakdown(offer)
    return _legacy_breakdown(offer)


# --- algoritmo Sprint 2 ---------------------------------------------------

def _category_aware_breakdown(offer: 'Offer') -> ScoreBreakdown:
    component_discount = _score_discount(offer.discount_pct) * WEIGHT_DISCOUNT
    component_popularity = _score_popularity(offer) * WEIGHT_POPULARITY
    component_reviews = _score_reviews(offer) * WEIGHT_REVIEWS
    component_price = _score_price(offer) * WEIGHT_PRICE
    component_category = _score_category(offer) * WEIGHT_CATEGORY

    components = {
        'discount': component_discount,
        'popularity': component_popularity,
        'reviews': component_reviews,
        'price': component_price,
        'category': component_category,
    }
    base = sum(components.values())

    multipliers = {
        'marketplace_trust': _marketplace_trust(offer),
        'recency': _score_recency(offer.last_seen_at),
    }
    if _is_test_controlled(offer):
        multipliers['test_controlled_confidence'] = PENALTY_TEST_CONTROLLED_CONFIDENCE

    penalties: dict[str, float] = {}
    if not (offer.image_url or '').strip():
        penalties['no_image'] = PENALTY_NO_IMAGE
    if _has_suspect_original_price(offer):
        penalties['suspect_original_price'] = PENALTY_SUSPECT_PRICE
    if _is_extreme_discount(offer.discount_pct):
        penalties['extreme_discount'] = PENALTY_EXTREME_DISCOUNT

    soft_penalties = evaluate_soft_penalties(offer)
    penalties.update(soft_penalties)

    multiplier = 1.0
    for value in multipliers.values():
        multiplier *= value
    for value in penalties.values():
        multiplier *= value

    final = max(0.0, min(100.0, base * multiplier))
    classification, decision = _classify_score(final)
    notes = _build_notes(penalties, multipliers)

    return ScoreBreakdown(
        score=final,
        components=components,
        penalties=penalties,
        multipliers=multipliers,
        classification=classification,
        decision=decision,
        notes=notes,
    )


def _build_notes(penalties: dict[str, float], multipliers: dict[str, float]) -> list[str]:
    notes: list[str] = []
    for key, value in penalties.items():
        if value >= 1.0:
            continue
        if key == 'no_image':
            notes.append(f'sem imagem (x{value:.2f})')
        elif key == 'suspect_original_price':
            notes.append(f'preço original suspeito (x{value:.2f})')
        elif key == 'extreme_discount':
            notes.append(f'desconto extremo >99% (x{value:.2f})')
        elif key == 'weak_signal':
            notes.append(
                'sinal fraco: desconto baixo + categoria fria + sem marca conhecida '
                f'(x{value:.2f})'
            )
        elif key.startswith('soft:'):
            notes.append(f'termo penalizado "{key[5:]}" (x{value:.2f})')
        else:
            notes.append(f'{key} (x{value:.2f})')

    if multipliers.get('test_controlled_confidence', 1.0) < 1.0:
        notes.append(
            f'categoria de teste controlado '
            f'(x{multipliers["test_controlled_confidence"]:.2f})'
        )
    if multipliers.get('recency', 1.0) < 0.5:
        notes.append(f'oferta antiga (recency x{multipliers["recency"]:.2f})')
    return notes


def _score_discount(discount_pct: Decimal | None) -> float:
    if discount_pct is None:
        return 0.0
    pct = float(discount_pct)
    if pct <= 0:
        return 0.0
    if pct <= 50:
        return pct / 50.0
    if pct <= float(SUSPECT_DISCOUNT_THRESHOLD):
        return 1.0
    if pct <= float(EXTREME_DISCOUNT_THRESHOLD):
        return max(0.0, 1.0 - (pct - float(SUSPECT_DISCOUNT_THRESHOLD)) / 30.0)
    return 0.0


def _score_popularity(offer: 'Offer') -> float:
    # Combinação: categoria quente + marca conhecida + flag bestseller no payload.
    category_factor = _category_weight_factor(offer)  # 0.1..1.0
    brand_factor = 1.0 if _has_strong_brand(offer.title) else 0.55
    bestseller_factor = 1.0 if _is_bestseller_label(offer) else 0.85

    score = 0.5 * category_factor + 0.3 * brand_factor + 0.2 * bestseller_factor
    return max(0.0, min(1.0, score))


def _score_reviews(offer: 'Offer') -> float:
    rating = float(offer.review_rating) if offer.review_rating is not None else 0.0
    count = int(offer.review_count or 0)

    if rating <= 0 and count <= 0:
        # Sem sinal: 0.5 evita zerar ofertas válidas sem dado e não premia o desconhecido.
        return 0.5

    if rating <= 0:
        rating = 4.0  # contagem sem nota: assume nota média neutra.

    if rating < 3.5:
        rating_factor = 0.2
    elif rating < 4.0:
        rating_factor = 0.6
    elif rating < 4.5:
        rating_factor = 0.85
    else:
        rating_factor = 1.0

    if count <= 0:
        count_factor = 0.4
    elif count >= 1000:
        count_factor = 1.0
    else:
        count_factor = max(0.4, log10(1 + count) / log10(1001))

    return max(0.0, min(1.0, 0.7 * rating_factor + 0.3 * count_factor))


def _score_price(offer: 'Offer') -> float:
    # Atratividade para compra por impulso/familiar — faixa principal R$ 30..R$ 400.
    if offer.current_price is None:
        return 0.0
    price = float(offer.current_price)
    if price <= 0:
        return 0.0
    if price < 30:
        return 0.6
    if price <= 150:
        return 1.0
    if price <= 400:
        return 0.85
    if price <= 800:
        return 0.6
    if price <= 1500:
        return 0.35
    return 0.15


def _score_category(offer: 'Offer') -> float:
    # Único ponto de verdade: a partir do peso 1–10 da Category (Sprint 3).
    return _category_weight_factor(offer)


def _category_weight_factor(offer: 'Offer') -> float:
    if not getattr(offer, 'category_id', None):
        return 0.2  # ofertas sem categoria não devem ser premiadas.
    weight = resolve_category_weight(offer.category)
    return weight / float(CATEGORY_MAX_WEIGHT)


def _has_strong_brand(title: str) -> bool:
    normalized = (title or '').lower()
    return any(brand in normalized for brand in STRONG_BRANDS)


def _is_bestseller_label(offer: 'Offer') -> bool:
    payload = offer.raw_payload or {}
    label = str(payload.get('source_label') or payload.get('categoria_origem') or '').lower()
    if not label:
        return False
    return any(marker in label for marker in BESTSELLER_LABELS)


def _is_test_controlled(offer: 'Offer') -> bool:
    if not getattr(offer, 'category_id', None):
        return False
    return bool(offer.category.is_test_controlled)


def _marketplace_trust(offer: 'Offer') -> float:
    code = (offer.marketplace.code or '').lower() if offer.marketplace_id else ''
    return MARKETPLACE_TRUST.get(code, DEFAULT_MARKETPLACE_TRUST)


def _score_recency(last_seen_at) -> float:
    if last_seen_at is None:
        return 0.0
    max_age_hours = resolve_max_age_hours()
    age_seconds = (timezone.now() - last_seen_at).total_seconds()
    if age_seconds <= 0:
        return 1.0
    age_hours = age_seconds / 3600.0
    if age_hours >= max_age_hours:
        return 0.0
    return 1.0 - (age_hours / max_age_hours)


def _has_suspect_original_price(offer: 'Offer') -> bool:
    if offer.original_price is None or offer.current_price is None:
        return False
    if offer.current_price <= 0:
        return False
    ratio = Decimal(offer.original_price) / Decimal(offer.current_price)
    return ratio >= SUSPECT_PRICE_RATIO


def _is_extreme_discount(discount_pct: Decimal | None) -> bool:
    if discount_pct is None:
        return False
    return Decimal(discount_pct) > EXTREME_DISCOUNT_THRESHOLD


def _classify_score(score: float) -> tuple[str, str]:
    if score >= 85:
        return 'excelente', 'prioritizar'
    if score >= 70:
        return 'boa', 'publicar'
    if score >= 55:
        return 'mediana', 'fila_secundaria'
    return 'fraca', 'descartar'


def _category_scoring_enabled() -> bool:
    return bool(get_integer_setting(FEATURE_FLAG_KEY, 1))


# --- algoritmo legado (mantido como fallback via Setting) -----------------

LEGACY_WEIGHT_DISCOUNT = 35.0
LEGACY_WEIGHT_SAVING = 25.0
LEGACY_WEIGHT_IMAGE = 10.0
LEGACY_WEIGHT_TITLE = 10.0
LEGACY_WEIGHT_RECENCY = 10.0
LEGACY_WEIGHT_MARKETPLACE = 10.0


def _legacy_breakdown(offer: 'Offer') -> ScoreBreakdown:
    components = {
        'discount': _score_discount(offer.discount_pct) * LEGACY_WEIGHT_DISCOUNT,
        'saving': _score_saving(offer.absolute_saving) * LEGACY_WEIGHT_SAVING,
        'image': _score_image(offer.image_url) * LEGACY_WEIGHT_IMAGE,
        'title': _score_title(offer.title) * LEGACY_WEIGHT_TITLE,
        'recency': _score_recency(offer.last_seen_at) * LEGACY_WEIGHT_RECENCY,
        'marketplace': _marketplace_trust(offer) * LEGACY_WEIGHT_MARKETPLACE,
    }
    base = sum(components.values())

    penalties: dict[str, float] = {}
    if not (offer.image_url or '').strip():
        penalties['no_image'] = PENALTY_NO_IMAGE
    if _has_suspect_original_price(offer):
        penalties['suspect_original_price'] = PENALTY_SUSPECT_PRICE
    if _is_extreme_discount(offer.discount_pct):
        penalties['extreme_discount'] = PENALTY_EXTREME_DISCOUNT

    multiplier = 1.0
    for value in penalties.values():
        multiplier *= value

    final = max(0.0, min(100.0, base * multiplier))
    classification, decision = _classify_score(final)
    return ScoreBreakdown(
        score=final,
        components=components,
        penalties=penalties,
        multipliers={},
        classification=classification,
        decision=decision,
    )


def _score_saving(absolute_saving: float) -> float:
    if absolute_saving <= 0:
        return 0.0
    if absolute_saving >= 1000:
        return 1.0
    return log10(1 + absolute_saving) / log10(1001)


def _score_image(image_url: str) -> float:
    return 1.0 if (image_url or '').strip() else 0.0


def _score_title(title: str) -> float:
    cleaned = (title or '').strip()
    if not cleaned:
        return 0.0
    if len(cleaned) < 15:
        return 0.4
    if _is_shouty(cleaned):
        return 0.6
    return 1.0


def _is_shouty(title: str) -> bool:
    letters = [ch for ch in title if ch.isalpha()]
    if len(letters) < 10:
        return False
    uppercase = sum(1 for ch in letters if ch.isupper())
    return uppercase / len(letters) > 0.8
