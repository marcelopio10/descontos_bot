from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str = ''


def validate_candidate(candidate: dict, seen_hashes: set[str] | None = None, now: datetime | None = None) -> ValidationResult:
    now = now or __import__('django.utils.timezone', fromlist=['now']).now()
    if seen_hashes is not None and candidate.get('candidate_hash') in seen_hashes:
        return ValidationResult(False, 'duplicado')
    if candidate.get('valid_until') and candidate['valid_until'] <= now:
        return ValidationResult(False, 'comprovadamente vencido')
    if not str(candidate.get('benefit') or '').strip():
        return ValidationResult(False, 'benefício não identificável')
    if not str(candidate.get('activation_code') or candidate.get('activation_method') or '').strip():
        return ValidationResult(False, 'código ou ativação ausente')
    source = str(candidate.get('source_url') or '')
    destination = str(candidate.get('destination_url') or '')
    if not all(urlparse(value).scheme in {'http', 'https'} and urlparse(value).netloc for value in (source, destination)):
        return ValidationResult(False, 'URL de fonte/destino inválida')
    if not str(candidate.get('evidence') or '').strip():
        return ValidationResult(False, 'evidência insuficiente')
    return ValidationResult(True)


def final_validate(candidate, affiliate_url: str, published_hashes: set[str], now=None) -> ValidationResult:
    result = validate_candidate(candidate, published_hashes, now)
    if not result.accepted:
        return result
    if affiliate_url and not urlparse(affiliate_url).netloc:
        return ValidationResult(False, 'link afiliado ausente ou inválido')
    return ValidationResult(True)
