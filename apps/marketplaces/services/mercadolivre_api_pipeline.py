from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.marketplaces.services.search_query_planner import SearchQuery
from apps.offers.services.normalizer import OfferNormalizationError
from apps.offers.services.repository import OfferRepository
from apps.scraping.models import ScrapingItemResult
from scrapers.category_targets import flatten_urls, get_targets

from .mercadolivre_affiliate_adapter import ExistingAffiliateLinkEngineAdapter
from .mercadolivre_api_client import MercadoLivreApiClient, MercadoLivreApiError
from .mercadolivre_eligibility import MercadoLivreOfferEligibilityPolicy
from .mercadolivre_price_resolver import MercadoLivrePriceResolver
from .mercadolivre_product_normalizer import MercadoLivreProductNormalizer
from .mercadolivre_search_provider import MercadoLivreSearchProvider

log = logging.getLogger('apps.marketplaces.mercadolivre_pipeline')


@dataclass(frozen=True)
class MercadoLivrePipelineResult:
    total_collected: int
    total_valid: int
    total_created: int
    total_updated: int
    total_discarded: int
    errors: tuple[str, ...] = ()


class MercadoLivreApiPipeline:
    provider_name = 'mercadolivre_api'

    def __init__(
        self,
        *,
        marketplace,
        run,
        max_pages: int,
        client: MercadoLivreApiClient | None = None,
        search_provider: MercadoLivreSearchProvider | None = None,
        price_resolver: MercadoLivrePriceResolver | None = None,
        product_normalizer: MercadoLivreProductNormalizer | None = None,
        eligibility_policy: MercadoLivreOfferEligibilityPolicy | None = None,
        affiliate_adapter: ExistingAffiliateLinkEngineAdapter | None = None,
        repository: OfferRepository | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        self.marketplace = marketplace
        self.run = run
        self.max_pages = max_pages
        self.client = client or MercadoLivreApiClient()
        self.search_provider = search_provider or MercadoLivreSearchProvider(self.client)
        self.price_resolver = price_resolver or MercadoLivrePriceResolver(self.client)
        self.product_normalizer = product_normalizer or MercadoLivreProductNormalizer()
        self.eligibility_policy = eligibility_policy or MercadoLivreOfferEligibilityPolicy()
        self.affiliate_adapter = affiliate_adapter or ExistingAffiliateLinkEngineAdapter(
            affiliate_tag='',
            ml_cookie='',
            ml_csrf='',
        )
        self.repository = repository or OfferRepository()
        self.observed_at = observed_at or timezone.now()
        self._category_map = self._build_category_map()

    def run_collection(self) -> MercadoLivrePipelineResult:
        candidates = self.search_provider.search_many(
            self._build_requests(),
            max_pages=self.max_pages,
        )
        errors: list[str] = []
        valid = created = updated = discarded = 0
        category_counts: dict[str, int] = {}

        for sequence, item in enumerate(candidates, start=1):
            item_id = str(item.get('id') or '')
            saved_offer = None
            run_item = None
            try:
                bulk_error = item.get('_api_error')
                if bulk_error:
                    reason_code = 'item_not_found' if int(bulk_error) == 404 else 'bulk_item_error'
                    message = f'Item {item_id or "sem-id"} rejeitado pela API (HTTP {bulk_error}).'
                    self._record_result(
                        sequence=sequence,
                        item_id=item_id,
                        status=ScrapingItemResult.Status.FAILED,
                        reason_code=reason_code,
                        error_message=message,
                        original_url='',
                        source=self._source(item),
                    )
                    errors.append(f'{item_id or "sem-id"}:api_http_{bulk_error}')
                    discarded += 1
                    continue
                price = self.price_resolver.resolve(item)
                seller = self._load_seller(item)
                category_code = str(
                    item.get('_category_code') or item.get('_category_hint') or '',
                ).strip()
                if not category_code:
                    category_code = self._category_map.get(str(item.get('category_id') or ''), '')
                normalized = self.product_normalizer.normalize(
                    item,
                    marketplace=self.marketplace,
                    price=price,
                    seller=seller,
                    observed_at=self.observed_at,
                )
                decision = self.eligibility_policy.evaluate(
                    normalized,
                    category_code=category_code,
                    seller_reputation=(seller or {}).get('seller_reputation') or {},
                    allowed_seller_levels=set(settings.ML_API_ALLOWED_SELLER_LEVEL_IDS),
                    category_rules=get_targets('mercadolivre').get(category_code) or {},
                    category_count=category_counts.get(category_code, 0),
                )
                if not decision.eligible:
                    self._record_result(
                        sequence=sequence,
                        item_id=item_id,
                        status=ScrapingItemResult.Status.DISCARDED,
                        reason_code=decision.reason_code,
                        error_message=decision.reason,
                        original_url=normalized.product_url,
                        source=self._source(item),
                    )
                    discarded += 1
                    continue

                saved_offer, run_item, was_created = self.repository.save_original(
                    normalized,
                    run=self.run,
                    sequence=sequence,
                    observed_at=self.observed_at,
                    source=self._source(item),
                )
                category_counts[category_code] = category_counts.get(category_code, 0) + 1
                valid += 1
                created += int(was_created)
                updated += int(not was_created)
                affiliate = self.affiliate_adapter.generate_result(str(saved_offer.product_url))
                self.repository.attach_affiliate(
                    saved_offer,
                    affiliate_url=affiliate.url,
                    generated=affiliate.generated,
                    run_item=run_item,
                    observed_at=self.observed_at,
                    error_code=affiliate.error_code,
                    error_message=affiliate.error_code,
                )
                if not affiliate.generated:
                    errors.append(f'{item_id}:affiliate:{affiliate.error_code}')
            except MercadoLivreApiError as exc:
                message = f'{item_id or "sem-id"}:api_http_{exc.status_code or "network"}'
                errors.append(message)
                self._record_result(
                    sequence=sequence,
                    item_id=item_id,
                    status=ScrapingItemResult.Status.FAILED,
                    reason_code='api_error',
                    error_message=message,
                    original_url='',
                    source=self._source(item),
                )
                if exc.auth_error or exc.status_code in (401, 403):
                    raise
            except (OfferNormalizationError, ValueError) as exc:
                message = str(exc)[:500]
                self._record_result(
                    sequence=sequence,
                    item_id=item_id,
                    status=ScrapingItemResult.Status.DISCARDED,
                    reason_code='normalization_error',
                    error_message=message,
                    original_url='',
                    source=self._source(item),
                )
                discarded += 1
            except Exception as exc:  # noqa: BLE001 - item isolado não derruba lote
                message = f'{item_id or "sem-id"}:{type(exc).__name__}'
                errors.append(message)
                if saved_offer is not None and run_item is not None:
                    self.repository.attach_affiliate(
                        saved_offer,
                        affiliate_url='',
                        generated=False,
                        run_item=run_item,
                        observed_at=self.observed_at,
                        error_code='affiliate_generation_exception',
                        error_message=message,
                    )
                else:
                    self._record_result(
                        sequence=sequence,
                        item_id=item_id,
                        status=ScrapingItemResult.Status.FAILED,
                        reason_code='item_processing_error',
                        error_message=message,
                        original_url='',
                        source=self._source(item),
                    )

        return MercadoLivrePipelineResult(
            total_collected=len(candidates),
            total_valid=valid,
            total_created=created,
            total_updated=updated,
            total_discarded=discarded,
            errors=tuple(errors[:20]),
        )

    def _build_requests(self) -> list[dict[str, Any]]:
        requests_to_run: list[dict[str, Any]] = []
        try:
            from apps.marketplaces.services.search_radar import build_search_radar
            from apps.marketplaces.services.search_query_planner import build_search_plan

            radar = build_search_radar(lookback_hours=168, limit=30)
            plan = build_search_plan(
                radar,
                marketplaces=('mercadolivre',),
                max_queries=6,
            )
            for query in plan.directed_queries:
                requests_to_run.append({
                    'query_text': query.query_text,
                    'category_id': '',
                    'sort': '',
                    'provenance': {
                        'source_kind': query.source_kind,
                        'query_text': query.query_text,
                        'brand': query.brand,
                        'category_code': query.category_code,
                        'price_band': query.price_band,
                        'trust_hint': 'true',
                        'marketplace': 'mercadolivre',
                    },
                })
        except Exception as exc:
            log.warning(
                'Falha ao construir busca direcionada ML; seguindo por categoria. reason=%s',
                type(exc).__name__,
            )

        for target in flatten_urls('mercadolivre'):
            category_id = self._category_id_from_target(target.url)
            if not category_id:
                continue
            requests_to_run.append({
                'query_text': '',
                'category_id': category_id,
                'sort': '',
                'provenance': {
                    'source_kind': 'category_target',
                    'category_code': target.category_code,
                    'trust_hint': str(target.trust_hint).lower(),
                    'marketplace': 'mercadolivre',
                },
            })
        if not requests_to_run:
            requests_to_run.append({
                'query_text': '',
                'category_id': '',
                'sort': '',
                'provenance': {
                    'source_kind': 'api_fallback',
                    'marketplace': 'mercadolivre',
                },
            })
        return requests_to_run

    def _load_seller(self, item: dict[str, Any]) -> dict[str, Any]:
        seller = item.get('seller') if isinstance(item.get('seller'), dict) else {}
        seller_id = str(seller.get('id') or '').strip()
        if not seller_id:
            return {}
        try:
            return self.client.get_seller(seller_id)
        except MercadoLivreApiError as exc:
            if exc.status_code == 404:
                return {}
            raise

    def _record_result(
        self,
        *,
        sequence: int,
        item_id: str,
        status: str,
        reason_code: str,
        error_message: str,
        original_url: str,
        source: str,
    ) -> None:
        with transaction.atomic():
            ScrapingItemResult.objects.update_or_create(
                run=self.run,
                sequence=sequence,
                defaults={
                    'external_id': item_id,
                    'original_url': original_url,
                    'source': source,
                    'status': status,
                    'reason_code': reason_code,
                    'error_message': error_message[:2000],
                    'processed_at': self.observed_at,
                },
            )

    @staticmethod
    def _source(item: dict[str, Any]) -> str:
        provenance = item.get('_search_provenance') or {}
        return str(provenance.get('source_kind') or item.get('_collection_source') or 'mercadolivre_api')[:160]

    @staticmethod
    def _category_id_from_target(value: Any) -> str:
        if not isinstance(value, str):
            return ''
        parsed = parse_qs(urlparse(value).query)
        category = (parsed.get('category') or [''])[0]
        return category if category.startswith('MLB') else ''

    @staticmethod
    def _build_category_map() -> dict[str, str]:
        mapping: dict[str, str] = {}
        for category_code, config in get_targets('mercadolivre').items():
            for entry in config.get('urls', []):
                if len(entry) < 2:
                    continue
                category_id = MercadoLivreApiPipeline._category_id_from_target(entry[1])
                if category_id:
                    mapping[category_id] = category_code
        return mapping
