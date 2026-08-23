"""Persistência das vendas detalhadas do painel de afiliados do ML.

Complementa `mercadolivre.py` (relatório agregado por produto) — não o
substitui. Aqui cada linha é uma venda, com status e motivo de rejeição, que é o
que permite separar comissão aprovada de rejeitada e marcar compra própria.

Duas regras de ouro desta rotina:

1. **Idempotência por `sale_id`.** Reimportar a mesma janela atualiza o que
   mudou (tipicamente `IN_REVIEW` → `APPROVED`/`REJECTED`) e não duplica linha.
   Por isso ela pode rodar em timer semanal com janela sobreposta.
2. **A marcação manual de compra própria manda.** A ingestão nunca a
   sobrescreve. O automático só age sobre linha ainda não marcada, e só no caso
   que o dono confirmou em 2026-08-23: venda `REJECTED` é compra da casa, porque
   o ML não paga comissão nesses casos.

Fora de escopo de propósito: alimentar `AffiliateConversion`/`affiliate-summary.json`
a partir daqui. Os dois caminhos contariam a mesma venda duas vezes se o
relatório agregado do mesmo período também fosse importado. Unificar é decisão
de produto, não detalhe de implementação.
"""

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.analytics.models import (
    AffiliateImportBatch,
    AffiliateSource,
    MLAffiliateSale,
    OwnPurchaseSource,
)
from apps.analytics.services.ml_affiliate_sales_client import SaleRecord
from apps.offers.models import Offer

log = logging.getLogger(__name__)

ML_MARKETPLACE_CODES = ('mercadolivre', 'mercado_livre')

# Status que o dono confirmou ser, em 100% dos casos, compra da própria casa:
# o ML recusa comissão quando quem compra é o afiliado.
OWN_PURCHASE_STATUS = 'REJECTED'

# Casamento de título por Jaccard, no mesmo espírito do gate de similaridade do
# selector. Limiar alto porque título de venda e título de oferta vêm do mesmo
# anúncio — divergem por pouco. Errar aqui liga venda à oferta errada, que é
# pior do que não ligar.
TITLE_JACCARD_THRESHOLD = 0.7
TITLE_MIN_TOKENS = 4
TITLE_STOPWORDS = {
    'com', 'para', 'por', 'sem', 'dos', 'das', 'una', 'uma', 'kit',
    'original', 'novo', 'nova', 'unidades', 'unidade', 'promocao',
}

# Janela para trás na busca de oferta candidata: a venda acontece depois da
# publicação, nunca antes.
OFFER_LOOKBACK_DAYS = 120


@dataclass
class MLSalesIngestResult:
    batch: AffiliateImportBatch
    created: int = 0
    updated: int = 0
    status_changed: int = 0
    auto_marked_own: int = 0
    resolved_offers: int = 0
    warnings: list[str] = field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None

    @property
    def total(self) -> int:
        return self.created + self.updated


def ingest_ml_sales(
    records: list[SaleRecord],
    *,
    filename: str = '',
    commit: bool = True,
) -> MLSalesIngestResult:
    if not records:
        raise ValueError('Nenhuma venda recebida do painel — nada a importar.')

    period_start = min(r.sale_date for r in records)
    period_end = max(r.sale_date for r in records)
    payload_sha256 = _fingerprint(records)

    warnings: list[str] = []
    result_created = result_updated = 0
    status_changed = auto_marked = resolved = 0

    with transaction.atomic():
        batch = AffiliateImportBatch.objects.create(
            source=AffiliateSource.MERCADO_LIVRE,
            period_start=period_start,
            period_end=period_end,
            raw_filename=filename or 'dashboard/sales/general',
            payload_sha256=payload_sha256,
            notes='',
        )

        existing = {
            sale.sale_id: sale
            for sale in MLAffiliateSale.objects.filter(
                sale_id__in=[r.sale_id for r in records]
            )
        }
        resolver = _OfferResolver(period_start)
        own_stores = _stores_with_own_purchases()

        for record in records:
            sale = existing.get(record.sale_id)
            offer = resolver.resolve(record)
            if offer is not None:
                resolved += 1

            if sale is None:
                is_own = record.status.upper() == OWN_PURCHASE_STATUS
                MLAffiliateSale.objects.create(
                    batch=batch,
                    offer=offer,
                    sale_id=record.sale_id,
                    sale_date=record.sale_date,
                    product_title=record.product_name,
                    product_link=record.product_link,
                    external_ref=record.external_ref,
                    category_name=record.category_name,
                    store_name=record.store_name,
                    sale_value_brl=_money(record.sale_value),
                    sale_units=record.sale_units or 1,
                    commission_brl=_money(record.commission_value),
                    commission_pct=_money(record.commission_percentage),
                    sale_type=record.sale_type,
                    status=record.status,
                    status_detail=record.status_detail,
                    is_own_purchase=is_own,
                    own_purchase_source=(
                        OwnPurchaseSource.AUTO_REJECTED if is_own else OwnPurchaseSource.NONE
                    ),
                )
                result_created += 1
                if is_own:
                    auto_marked += 1
                elif record.store_name and record.store_name in own_stores:
                    warnings.append(
                        f'Venda nova da loja "{record.store_name}", que já teve compra '
                        f'própria marcada: {record.product_name[:60]} '
                        f'(R$ {record.commission_value:.2f}, {record.sale_date:%d/%m}). '
                        'Confira se não é compra da casa.'
                    )
                continue

            # Atualização: campos voláteis do painel, nunca a marcação manual.
            if sale.status != record.status:
                status_changed += 1
            sale.batch = batch
            sale.status = record.status
            sale.status_detail = record.status_detail
            sale.commission_brl = _money(record.commission_value)
            sale.commission_pct = _money(record.commission_percentage)
            sale.sale_value_brl = _money(record.sale_value)
            sale.sale_units = record.sale_units or 1
            if offer is not None and sale.offer_id is None:
                sale.offer = offer
            fields = [
                'batch', 'status', 'status_detail', 'commission_brl',
                'commission_pct', 'sale_value_brl', 'sale_units', 'offer',
                'updated_at',
            ]
            # Só o automático pode ser reavaliado — marcação manual é soberana.
            if sale.own_purchase_source != OwnPurchaseSource.MANUAL:
                should_be_own = record.status.upper() == OWN_PURCHASE_STATUS
                if should_be_own and not sale.is_own_purchase:
                    sale.is_own_purchase = True
                    sale.own_purchase_source = OwnPurchaseSource.AUTO_REJECTED
                    auto_marked += 1
                    fields += ['is_own_purchase', 'own_purchase_source']
            sale.save(update_fields=fields)
            result_updated += 1

        if resolver.unresolved:
            warnings.append(
                f'Vendas sem oferta correspondente ({len(resolver.unresolved)} de '
                f'{len(records)}): ' + ', '.join(resolver.unresolved[:10])
                + ('…' if len(resolver.unresolved) > 10 else '')
            )
        if resolver.catalog_links:
            warnings.append(
                f'{resolver.catalog_links} venda(s) com link de catálogo (/p/MLB…) — '
                'namespace diferente do external_id das ofertas, casadas só por título.'
            )

        batch.rows_imported = result_created + result_updated
        batch.rows_skipped = 0
        batch.notes = '\n'.join(warnings)
        batch.save(update_fields=['rows_imported', 'rows_skipped', 'notes'])

        if not commit:
            transaction.set_rollback(True)

    log.info(
        'ml_sales_ingest periodo=%s..%s criadas=%d atualizadas=%d status_mudou=%d '
        'compra_propria_auto=%d ofertas_resolvidas=%d',
        period_start, period_end, result_created, result_updated,
        status_changed, auto_marked, resolved,
    )

    return MLSalesIngestResult(
        batch=batch,
        created=result_created,
        updated=result_updated,
        status_changed=status_changed,
        auto_marked_own=auto_marked,
        resolved_offers=resolved,
        warnings=warnings,
        period_start=period_start,
        period_end=period_end,
    )


class _OfferResolver:
    """Liga venda → `Offer`, por MLB quando dá e por título quando não dá.

    O join por ID não cobre o caso do link de catálogo (`/p/MLB…`), que era 33
    de 74 vendas na amostra de 2026-08-23, e uma fatia das nossas ofertas de ML é
    guardada com pseudo-id por slug. Por isso o título é o caminho principal, não
    o de exceção.
    """

    def __init__(self, period_start: date):
        floor = period_start - timedelta(days=OFFER_LOOKBACK_DAYS)
        self._by_external: dict[str, Offer] = {}
        self._by_tokens: list[tuple[frozenset[str], Offer]] = []
        self.unresolved: list[str] = []
        self.catalog_links = 0

        queryset = Offer.objects.filter(
            marketplace__code__in=ML_MARKETPLACE_CODES,
            first_seen_at__gte=floor,
        ).only('id', 'external_id', 'title', 'normalized_title')

        for offer in queryset.iterator(chunk_size=2000):
            external = (offer.external_id or '').upper()
            if external:
                self._by_external.setdefault(external, offer)
            tokens = _tokens(offer.normalized_title or offer.title or '')
            if len(tokens) >= TITLE_MIN_TOKENS:
                self._by_tokens.append((frozenset(tokens), offer))

    def resolve(self, record: SaleRecord) -> Offer | None:
        if '/p/MLB' in (record.product_link or ''):
            self.catalog_links += 1

        external = record.external_ref
        if external and external in self._by_external:
            return self._by_external[external]

        tokens = _tokens(record.product_name)
        if len(tokens) >= TITLE_MIN_TOKENS:
            best_offer = None
            best_score = 0.0
            token_set = frozenset(tokens)
            for candidate_tokens, offer in self._by_tokens:
                union = token_set | candidate_tokens
                if not union:
                    continue
                score = len(token_set & candidate_tokens) / len(union)
                if score > best_score:
                    best_score, best_offer = score, offer
            if best_offer is not None and best_score >= TITLE_JACCARD_THRESHOLD:
                return best_offer

        self.unresolved.append(record.product_name[:40] or record.sale_id)
        return None


def _stores_with_own_purchases() -> set[str]:
    return set(
        MLAffiliateSale.objects.filter(is_own_purchase=True)
        .exclude(store_name='')
        .values_list('store_name', flat=True)
        .distinct()
    )


def _tokens(text: str) -> set[str]:
    normalized = _strip_accents(text or '').lower()
    return {
        token
        for token in re.findall(r'[a-z0-9]+', normalized)
        if len(token) >= 3 and token not in TITLE_STOPWORDS
    }


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _money(value) -> Decimal:
    return Decimal(str(round(float(value or 0), 2)))


def _fingerprint(records: list[SaleRecord]) -> str:
    """sha256 do conteúdo normalizado.

    Ao contrário do parser agregado, um sha repetido **não** é erro aqui: a
    rotina roda em timer com janela sobreposta e a idempotência é por `sale_id`.
    O hash serve para rastrear no lote o que exatamente foi recebido.
    """
    canonical = json.dumps(
        [
            [r.sale_id, r.status, r.commission_value, r.sale_value]
            for r in sorted(records, key=lambda x: x.sale_id)
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
