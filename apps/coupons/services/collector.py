from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from .firecrawl_client import FirecrawlClient, CouponSourceError

MARKETPLACES = {
    'mercadolivre': ('Mercado Livre', 'site:mercadolivre.com.br cupom desconto'),
    'amazon': ('Amazon', 'site:amazon.com.br cupom desconto'),
    'shopee': ('Shopee', 'site:shopee.com.br cupom desconto'),
    'shein': ('SHEIN', 'site:shein.com.br cupom desconto'),
}
CODE_RE = re.compile(r'(?i)(?:c[oó]digo|cupom|use)\s*[:\-]?\s*([A-Z0-9][A-Z0-9_-]{3,})')
PERCENT_RE = re.compile(r'(?i)(\d{1,3})\s*%\s*(?:off|de desconto|desconto)')
MIN_RE = re.compile(r'(?i)(?:acima de|a partir de|compra m[ií]nima|m[ií]nimo de)\s*R?\$?\s*([\d.,]+)')
MAX_RE = re.compile(r'(?i)(?:at[eé]|m[aá]ximo de|limitado a)\s*R?\$?\s*([\d.,]+)')
DATE_RE = re.compile(r'(?i)(?:validade|v[aá]lido at[eé]|at[eé])\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})')


def _money(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace('.', '').replace(',', '.'))
    except Exception:
        return None


def _date(value: str | None):
    if not value:
        return None
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return timezone.make_aware(datetime.strptime(value, fmt))
        except ValueError:
            pass
    return None


def normalize_candidate(marketplace: str, page_url: str, text: str, destination_url: str | None = None) -> dict[str, Any]:
    code_match = CODE_RE.search(text)
    percent_match = PERCENT_RE.search(text)
    min_match = MIN_RE.search(text)
    max_match = MAX_RE.search(text)
    date_match = DATE_RE.search(text)
    code = code_match.group(1).upper() if code_match else ''
    benefit = percent_match.group(0).strip() if percent_match else ''
    if not benefit:
        money = re.search(r'(?i)R\$\s*[\d.,]+\s*(?:de desconto|off)', text)
        benefit = money.group(0).strip() if money else ''
    activation = f'Aplicar o código {code}' if code else ''
    digest = hashlib.sha256(f'{marketplace}|{code}|{benefit}|{page_url}'.encode()).hexdigest()
    return {
        'candidate_hash': digest,
        'marketplace': marketplace,
        'activation_code': code,
        'activation_method': activation,
        'benefit': benefit,
        'minimum_purchase': _money(min_match.group(1)) if min_match else None,
        'maximum_discount': _money(max_match.group(1)) if max_match else None,
        'restrictions': _restrictions(text),
        'valid_until': _date(date_match.group(1)) if date_match else None,
        'source_url': page_url,
        'campaign_url': page_url,
        'destination_url': destination_url or page_url,
        'affiliate_url': os.environ.get(f'COUPON_AFFILIATE_URL_{marketplace.upper()}', ''),
        'evidence': text[:8000],
    }


def _restrictions(text: str) -> list[str]:
    hits = []
    for pattern in (r'primeira compra[^.]*', r'frete[^.]*', r'categor[^.]*', r'produto[^.]*', r'conta[^.]*', r'cliente[^.]*'):
        match = re.search(pattern, text, re.I)
        if match:
            hits.append(' '.join(match.group(0).split()))
    return hits[:8]


def collect_marketplaces(client: FirecrawlClient | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    client = client or FirecrawlClient()
    candidates, sources, errors = [], [], []
    for code, (label, query) in MARKETPLACES.items():
        try:
            pages = client.search(query, limit=5)
            sources.append({'marketplace': code, 'provider': pages[0].provider if pages else 'none', 'count': str(len(pages))})
            for page in pages:
                detail = client.scrape(page.url)
                candidate = normalize_candidate(code, page.url, detail.markdown)
                if candidate['benefit'] or candidate['activation_code']:
                    candidates.append(candidate)
        except CouponSourceError as exc:
            errors.append({'marketplace': code, 'error': str(exc)})
        except Exception as exc:
            errors.append({'marketplace': code, 'error': f'{type(exc).__name__}: {exc}'})
    return candidates, sources + [{'errors': errors}] if errors else sources
