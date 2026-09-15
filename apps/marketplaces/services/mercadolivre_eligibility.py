from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.offers.services.normalizer import NormalizedOffer


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason_code: str = ''
    reason: str = ''


class MercadoLivreOfferEligibilityPolicy:
    def evaluate(
        self,
        normalized_offer: NormalizedOffer,
        *,
        category_code: str,
        seller_reputation: dict[str, Any] | None,
        allowed_seller_levels: set[str],
        category_rules: dict[str, Any] | None = None,
        category_count: int = 0,
    ) -> EligibilityResult:
        rules = category_rules or {}
        status = normalized_offer.listing_status.strip().lower()
        if status != 'active':
            return EligibilityResult(False, 'inactive', 'Anúncio não está ativo.')

        condition = normalized_offer.condition.strip().lower()
        if condition != 'new':
            return EligibilityResult(False, 'condition_not_new', 'Produto não é novo.')

        if not normalized_offer.seller_id:
            return EligibilityResult(False, 'seller_reputation_missing', 'Vendedor sem identificador.')
        reputation = seller_reputation or {}
        level_id = str(reputation.get('level_id') or '').strip()
        if not level_id:
            return EligibilityResult(False, 'seller_reputation_missing', 'Reputação do vendedor ausente.')
        if allowed_seller_levels and level_id not in allowed_seller_levels:
            return EligibilityResult(False, 'seller_not_eligible', 'Nível de reputação não permitido.')
        if not allowed_seller_levels:
            return EligibilityResult(False, 'seller_not_eligible', 'Níveis de reputação permitidos não configurados.')

        if not category_code or not rules:
            return EligibilityResult(False, 'category_not_allowed', 'Categoria do anúncio não permitida.')
        if normalized_offer.currency_code.upper() != 'BRL':
            return EligibilityResult(False, 'invalid_currency', 'Moeda diferente de BRL.')
        if normalized_offer.current_price <= Decimal('0'):
            return EligibilityResult(False, 'invalid_price', 'Preço vigente inválido.')
        quantity = normalized_offer.available_quantity
        if quantity is not None:
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                return EligibilityResult(False, 'invalid_quantity', 'Quantidade disponível inválida.')
            if quantity == 0:
                return EligibilityResult(False, 'unavailable', 'Anúncio sem disponibilidade.')

        min_discount = Decimal(str(rules.get('min_discount', 0) or 0))
        max_price = rules.get('max_price')
        cycle_limit = int(rules.get('cycle_limit', 0) or 0)
        if cycle_limit > 0 and category_count >= cycle_limit:
            return EligibilityResult(False, 'cycle_limit', 'Limite da categoria atingido no ciclo.')
        if max_price is not None and normalized_offer.current_price > Decimal(str(max_price)):
            return EligibilityResult(False, 'category_not_allowed', 'Preço acima do teto da categoria.')
        if normalized_offer.original_price is None and min_discount > 0:
            return EligibilityResult(False, 'missing_price_reference', 'Preço de referência ausente.')
        if (normalized_offer.discount_pct or Decimal('0')) < min_discount:
            return EligibilityResult(False, 'discount_below_minimum', 'Desconto abaixo do mínimo configurado.')

        return EligibilityResult(True)
