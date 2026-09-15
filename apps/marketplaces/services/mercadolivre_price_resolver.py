from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from django.conf import settings

from .mercadolivre_api_client import MercadoLivreApiClient, MercadoLivreApiError


@dataclass(frozen=True)
class PriceSnapshot:
    current_price: Decimal
    original_price: Decimal | None
    discount_pct: Decimal
    currency_code: str
    source: str
    reference_date: str = ''
    error_code: str = ''


class MercadoLivrePriceResolver:
    def __init__(self, client: MercadoLivreApiClient | None = None) -> None:
        self.client = client or MercadoLivreApiClient()

    def resolve(self, item: dict[str, Any]) -> PriceSnapshot:
        item_id = str(item.get('id') or '').strip()
        item_price = self._money(item.get('price'))
        item_reference = self._first_valid_reference(
            item.get('original_price'),
            item.get('base_price'),
        )
        currency = str(item.get('currency_id') or '').strip().upper()
        current = item_price
        reference = item_reference
        source = 'item'
        reference_date = ''
        error_code = ''

        if getattr(settings, 'ML_API_CONTEXTUAL_PRICE_ENABLED', True) and item_id:
            try:
                contextual = self.client.get_sale_price(
                    item_id,
                    settings.ML_API_CONTEXT,
                )
                contextual_current = self._money(contextual.get('amount'))
                contextual_reference = self._first_valid_reference(contextual.get('regular_amount'))
                if contextual_current is not None:
                    current = contextual_current
                    if contextual_reference is not None:
                        reference = contextual_reference
                    currency = str(contextual.get('currency_id') or currency).strip().upper()
                    reference_date = str(contextual.get('reference_date') or '')
                    source = 'sale_price'
            except MercadoLivreApiError as exc:
                if exc.status_code in (401, 403):
                    raise
                if exc.status_code not in (400, 404) and not exc.retryable:
                    raise
                error_code = 'contextual_price_unavailable'

        if current is None or current <= Decimal('0'):
            raise ValueError('Preço vigente ausente ou inválido.')
        if reference is not None and reference <= current:
            reference = None
        discount = Decimal('0.00')
        if reference is not None and reference > current:
            discount = ((reference - current) / reference * Decimal('100')).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )

        return PriceSnapshot(
            current_price=current.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            original_price=(reference.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if reference else None),
            discount_pct=discount,
            currency_code=currency,
            source=source,
            reference_date=reference_date,
            error_code=error_code,
        )

    @staticmethod
    def _money(value: Any) -> Decimal | None:
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError):
            return None

    def _first_valid_reference(self, *values: Any) -> Decimal | None:
        for value in values:
            parsed = self._money(value)
            if parsed is not None and parsed > Decimal('0'):
                return parsed
        return None
