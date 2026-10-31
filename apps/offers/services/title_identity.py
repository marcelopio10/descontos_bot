from __future__ import annotations

import re
import unicodedata


SIMILAR_TITLE_MIN_TOKENS = 4
SIMILAR_TITLE_JACCARD_THRESHOLD = 0.75

# Palavras já descartadas pelo selector antes desta extração. Mantê-las aqui
# deixa a identidade editorial independente de Offer.normalized_title, que é
# um campo legado com contrato próprio.
TITLE_STOPWORDS = frozenset({
    'com',
    'para',
    'por',
    'sem',
    'masculino',
    'masculina',
    'feminino',
    'feminina',
})

# Ruído promocional comprovado nos títulos coletados e já tratado pela lógica
# de família. A lista é deliberadamente curta para não fundir produtos por
# adjetivos comerciais que também podem identificar uma variante real.
PROMOTIONAL_NOISE = frozenset({
    'anuncio',
    'patrocinado',
    'oferta',
    'promocao',
    'desconto',
    'frete',
    'gratis',
})

_IGNORED_TOKENS = TITLE_STOPWORDS | PROMOTIONAL_NOISE
_TOKEN_RE = re.compile(r'[a-z0-9]+')
_SPONSORED_PREFIX_RE = re.compile(
    r'^\s*an[uú]ncio\s+patrocinado\s*[\-–—:]?\s*',
    re.IGNORECASE,
)


def normalize_title_surface(value: str) -> str:
    """Remove variações gráficas sem descartar palavras semanticamente úteis."""
    without_sponsored_prefix = _SPONSORED_PREFIX_RE.sub(
        '',
        str(value or '').replace('\u00ad', ''),
    )
    decomposed = unicodedata.normalize('NFKD', without_sponsored_prefix)
    ascii_text = decomposed.encode('ascii', 'ignore').decode('ascii').lower()
    return ' '.join(_TOKEN_RE.findall(ascii_text))


def normalize_editorial_title(value: str) -> str:
    """Normaliza um título para comparação editorial, sem persistir mudanças."""
    without_sponsored_prefix = _SPONSORED_PREFIX_RE.sub(
        '',
        str(value or '').replace('\u00ad', ''),
    )
    decomposed = unicodedata.normalize('NFKD', without_sponsored_prefix)
    comparable_text = ''.join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    ).lower()
    tokens = (
        token
        for token in _TOKEN_RE.findall(comparable_text)
        if token not in _IGNORED_TOKENS
    )
    return ' '.join(tokens)


def strong_title_similarity(first: str, second: str) -> bool:
    """Compara identidade exata normalizada ou Jaccard forte entre títulos."""
    first_normalized = normalize_editorial_title(first)
    second_normalized = normalize_editorial_title(second)
    if not first_normalized or not second_normalized:
        return False
    if first_normalized == second_normalized:
        return True

    first_tokens = _similarity_tokens(first_normalized)
    second_tokens = _similarity_tokens(second_normalized)
    if (
        len(first_tokens) < SIMILAR_TITLE_MIN_TOKENS
        or len(second_tokens) < SIMILAR_TITLE_MIN_TOKENS
    ):
        return False

    union = first_tokens | second_tokens
    if not union:
        return False
    similarity = len(first_tokens & second_tokens) / len(union)
    return similarity >= SIMILAR_TITLE_JACCARD_THRESHOLD


def _similarity_tokens(normalized_title: str) -> set[str]:
    return {
        token
        for token in normalized_title.split()
        if len(token) >= 3
    }
