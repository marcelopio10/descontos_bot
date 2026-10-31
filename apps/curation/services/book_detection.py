from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from apps.offers.services.title_identity import normalize_editorial_title


@dataclass(frozen=True)
class BookDetectionResult:
    is_book: bool
    confidence: float
    signals: tuple[str, ...]


_SIGNAL_CONFIDENCE = {
    'isbn': 1.0,
    'metadata_category': 0.98,
    'metadata_product_type': 0.98,
    'metadata_browse_node': 0.97,
    'metadata_format': 0.96,
    'title_book': 0.90,
}
_SIGNAL_ORDER = tuple(_SIGNAL_CONFIDENCE)

_CATEGORY_KEYS = frozenset({
    'category',
    'category_name',
    'category_label',
    'category_hint',
    'source_label',
})
_PRODUCT_TYPE_KEYS = frozenset({
    'product_type',
    'product_type_name',
    'item_type',
    'item_type_name',
    'domain_id',
})
_BROWSE_NODE_KEYS = frozenset({
    'browse_node',
    'browse_node_name',
    'browse_path',
    'department',
})
_FORMAT_KEYS = frozenset({
    'binding',
    'format',
    'formato',
    'media_type',
    'edition_type',
})
_FORMAT_ATTRIBUTE_TERMS = frozenset({
    'binding',
    'edition type',
    'format',
    'formato',
    'media type',
})
_ISBN_KEYS = frozenset({
    'isbn',
    'isbn_10',
    'isbn10',
    'isbn_13',
    'isbn13',
})
_NESTED_METADATA_KEYS = (
    'api_item',
    'item',
    'product',
    'metadata',
)
_KNOWN_BOOK_CATEGORY_IDS = frozenset({
    'MLB1196',
})
_BOOK_TAXONOMY_HEADS = frozenset({
    'book',
    'books',
    'ebook',
    'ebooks',
    'livro',
    'livros',
})
_BOOK_TAXONOMY_EXACT = frozenset({
    *_BOOK_TAXONOMY_HEADS,
    'audio book',
    'audiobook',
    'audiobooks',
    'digital book',
    'e book',
    'e books',
    'kindle book',
    'kindle books',
    'physical book',
    'printed book',
})
_BOOK_FORMATS = (
    'capa comum',
    'capa dura',
    'paperback',
    'hardcover',
    'brochura',
    'edicao kindle',
    'kindle edition',
    'livro digital',
    'e book',
    'ebook',
)
_ACCESSORY_TERMS = frozenset({
    'acessorio',
    'acessorios',
    'accessories',
    'accessory',
    'bag',
    'bags',
    'capa protetora',
    'case',
    'cover',
    'covers',
    'holder',
    'holders',
    'lamp',
    'lamps',
    'leitor',
    'light',
    'lights',
    'marcador',
    'organizador',
    'organizadora',
    'organizer',
    'organizers',
    'pelicula',
    'porta livro',
    'reader',
    'readers',
    'sleeve',
    'sleeves',
    'stand',
    'stands',
    'storage',
    'suporte',
})
_NON_BOOK_PRODUCT_TERMS = frozenset({
    *_ACCESSORY_TERMS,
    'album',
    'bolsa',
    'brinquedo',
    'camiseta',
    'carrinho',
    'estante',
    'fichario',
    'jogo',
    'luminaria',
    'mochila',
    'organizador',
    'organizadora',
    'pasta',
    'prateleira',
    'sapateira',
})
_BOOK_TITLE_CONTEXTS = frozenset({
    'ao livro',
    'aos livros',
    'capa comum',
    'capa dura',
    'edicao',
    'livro da',
    'livro das',
    'livro de',
    'livro de pano',
    'livro do',
    'livro dos',
    'o livro',
    'os livros',
    'paginas',
    'um livro',
    'volume',
    'volumes',
})
_KINDLE_TITLE_CONTEXTS = frozenset({
    'e book kindle',
    'ebook kindle',
    'edicao kindle',
    'livro kindle',
    'versao kindle',
})
_ATTRIBUTE_KEYS = ('id', 'name', 'nome')
_ATTRIBUTE_VALUE_KEYS = ('value_name', 'value', 'values')
_ISBN_CANDIDATE_RE = re.compile(r'[0-9Xx][0-9Xx\- ]{8,20}[0-9Xx]')
_MAX_METADATA_DEPTH = 3


def detect_book_offer(offer) -> BookDetectionResult:
    """Retorna detecção auditável de livro sem expor valores da oferta."""
    signals: set[str] = set()
    raw_payload = getattr(offer, 'raw_payload', {})
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    containers = tuple(_iter_metadata_containers(payload))

    category = getattr(offer, 'category', None)
    category_values = (
        getattr(category, 'code', ''),
        getattr(category, 'name', ''),
    )
    if any(_is_book_taxonomy_value(value) for value in category_values):
        signals.add('metadata_category')

    if _containers_have_book_value(containers, _CATEGORY_KEYS):
        signals.add('metadata_category')
    if _containers_have_known_category_id(containers):
        signals.add('metadata_category')
    if _containers_have_book_value(containers, _PRODUCT_TYPE_KEYS):
        signals.add('metadata_product_type')
    if _containers_have_book_value(containers, _BROWSE_NODE_KEYS):
        signals.add('metadata_browse_node')
    if _containers_have_book_format(containers):
        signals.add('metadata_format')
    if _containers_have_isbn(containers):
        signals.add('isbn')

    attribute_signals = _attribute_signals(containers)
    signals.update(attribute_signals)

    title = str(
        getattr(offer, 'title', '')
        or getattr(offer, 'normalized_title', '')
        or ''
    )
    if _title_has_valid_isbn(title):
        signals.add('isbn')
    if _is_strong_book_title(title):
        signals.add('title_book')

    ordered_signals = tuple(
        signal
        for signal in _SIGNAL_ORDER
        if signal in signals
    )
    confidence = max(
        (_SIGNAL_CONFIDENCE[signal] for signal in ordered_signals),
        default=0.0,
    )
    return BookDetectionResult(
        is_book=bool(ordered_signals),
        confidence=confidence,
        signals=ordered_signals,
    )


def _iter_metadata_containers(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield payload
    for key in _NESTED_METADATA_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            yield nested


def _containers_have_book_value(
    containers: tuple[dict[str, Any], ...],
    keys: frozenset[str],
) -> bool:
    return any(
        _is_book_taxonomy_value(value)
        for container in containers
        for key, value in container.items()
        if isinstance(key, str) and key.casefold() in keys
        for value in _metadata_values(value)
    )


def _containers_have_known_category_id(
    containers: tuple[dict[str, Any], ...],
) -> bool:
    for container in containers:
        for key in ('category_id', '_category_id'):
            value = container.get(key)
            if isinstance(value, str) and value.strip().upper() in _KNOWN_BOOK_CATEGORY_IDS:
                return True
    return False


def _containers_have_book_format(
    containers: tuple[dict[str, Any], ...],
) -> bool:
    return any(
        _is_book_format(value)
        for container in containers
        for key, value in container.items()
        if isinstance(key, str) and key.casefold() in _FORMAT_KEYS
        for value in _metadata_values(value)
    )


def _containers_have_isbn(
    containers: tuple[dict[str, Any], ...],
) -> bool:
    return any(
        _contains_valid_isbn(candidate)
        for container in containers
        for key, value in container.items()
        if isinstance(key, str) and key.casefold() in _ISBN_KEYS
        for candidate in _metadata_values(value)
    )


def _attribute_signals(
    containers: tuple[dict[str, Any], ...],
) -> set[str]:
    signals: set[str] = set()
    for container in containers:
        attributes = container.get('attributes')
        if not isinstance(attributes, list):
            continue
        for attribute in attributes[:50]:
            if not isinstance(attribute, dict):
                continue
            names = [
                str(attribute.get(key) or '')
                for key in _ATTRIBUTE_KEYS
            ]
            normalized_name = ' '.join(
                normalize_editorial_title(name)
                for name in names
                if name
            )
            values = [
                attribute.get(key)
                for key in _ATTRIBUTE_VALUE_KEYS
                if key in attribute
            ]
            if 'isbn' in normalized_name and any(
                _contains_valid_isbn(candidate)
                for raw_value in values
                for candidate in _metadata_values(raw_value)
            ):
                signals.add('isbn')
            if any(
                term in normalized_name
                for term in _FORMAT_ATTRIBUTE_TERMS
            ) and any(
                _is_book_format(value)
                for raw_value in values
                for value in _metadata_values(raw_value)
            ):
                signals.add('metadata_format')
            if any(
                term in normalized_name
                for term in ('item type', 'product type', 'tipo de produto')
            ) and any(
                _is_book_taxonomy_value(value)
                for raw_value in values
                for value in _metadata_values(raw_value)
            ):
                signals.add('metadata_product_type')
            if 'browse node' in normalized_name and any(
                _is_book_taxonomy_value(value)
                for raw_value in values
                for value in _metadata_values(raw_value)
            ):
                signals.add('metadata_browse_node')
            if any(
                term in normalized_name
                for term in ('categoria', 'category')
            ) and any(
                _is_book_taxonomy_value(value)
                for raw_value in values
                for value in _metadata_values(raw_value)
            ):
                signals.add('metadata_category')
    return signals


def _metadata_values(
    value: Any,
    *,
    depth: int = 0,
) -> Iterable[Any]:
    if depth > _MAX_METADATA_DEPTH:
        return
    if isinstance(value, dict):
        for key in (
            'id',
            'code',
            'name',
            'label',
            'value',
            'value_name',
            'values',
        ):
            if key in value:
                yield from _metadata_values(value[key], depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value[:20]:
            yield from _metadata_values(item, depth=depth + 1)
        return
    yield value


def _is_book_taxonomy_value(value: Any) -> bool:
    normalized = normalize_editorial_title(_bounded_text(value))
    if not normalized:
        return False
    if _contains_any_phrase(normalized, _ACCESSORY_TERMS):
        return False
    if normalized in _BOOK_TAXONOMY_EXACT:
        return True
    tokens = normalized.split()
    return bool(
        tokens
        and (
            tokens[0] in _BOOK_TAXONOMY_HEADS
            or 'literatura' in tokens
            or normalized.startswith('e book ')
        )
    )


def _is_book_format(value: Any) -> bool:
    normalized = normalize_editorial_title(_bounded_text(value))
    return any(
        normalized == book_format
        or normalized.startswith(f'{book_format} ')
        or normalized.endswith(f' {book_format}')
        for book_format in _BOOK_FORMATS
    )


def _is_strong_book_title(title: str) -> bool:
    normalized = normalize_editorial_title(title)
    if not normalized:
        return False

    tokens = normalized.split()
    token_set = set(tokens)
    book_positions = [
        index
        for index, token in enumerate(tokens)
        if token in {'livro', 'livros'}
    ]
    if book_positions:
        first_book_position = book_positions[0]
        prefix = ' '.join(tokens[:first_book_position])
        if not _contains_any_phrase(prefix, _NON_BOOK_PRODUCT_TERMS):
            if first_book_position <= 3:
                return True
            if _contains_any_phrase(
                normalized,
                _BOOK_TITLE_CONTEXTS,
            ):
                return True
            if tokens[0] in {'box', 'colecao', 'kit'} and any(
                token.isdigit()
                for token in tokens[:first_book_position]
            ):
                return True

    if 'kindle' in token_set and _contains_any_phrase(
        normalized,
        _KINDLE_TITLE_CONTEXTS,
    ):
        return True

    if (
        normalized.startswith('ebook ')
        or normalized.startswith('e book ')
        or 'livro digital' in normalized
    ) and not _contains_any_phrase(normalized, _ACCESSORY_TERMS):
        return True

    return False


def _title_has_valid_isbn(title: str) -> bool:
    normalized = normalize_editorial_title(title)
    if 'isbn' not in normalized:
        return False
    return _contains_valid_isbn(title)


def _contains_valid_isbn(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    text = _bounded_text(value)
    candidates = [text, *_ISBN_CANDIDATE_RE.findall(text)]
    return any(_is_valid_isbn(candidate) for candidate in candidates)


def _is_valid_isbn(value: str) -> bool:
    compact = re.sub(r'[^0-9Xx]', '', value).upper()
    if len(compact) == 10:
        if not compact[:9].isdigit() or not (compact[-1].isdigit() or compact[-1] == 'X'):
            return False
        digits = [int(character) for character in compact[:9]]
        check_digit = 10 if compact[-1] == 'X' else int(compact[-1])
        checksum = sum(
            weight * digit
            for weight, digit in zip(range(10, 1, -1), digits, strict=True)
        ) + check_digit
        return checksum % 11 == 0
    if (
        len(compact) == 13
        and compact.isdigit()
        and compact.startswith(('978', '979'))
    ):
        total = sum(
            int(character) * (1 if index % 2 == 0 else 3)
            for index, character in enumerate(compact)
        )
        return total % 10 == 0
    return False


def _bounded_text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ''
    if isinstance(value, (dict, list, tuple, set)):
        return ''
    return str(value).strip()[:500]


def _contains_any_phrase(text: str, phrases: Iterable[str]) -> bool:
    padded_text = f' {text} '
    return any(f' {phrase} ' in padded_text for phrase in phrases)
