from __future__ import annotations

import re
from typing import Any, Iterable

from django.conf import settings

from .mercadolivre_api_client import MercadoLivreApiClient, MercadoLivreApiError

ML_ITEM_ID_RE = re.compile(r'^MLB[0-9]+$')


class MercadoLivreSearchProvider:
    """Busca e hidrata anúncios do catálogo público do Mercado Livre."""

    def __init__(
        self,
        client: MercadoLivreApiClient | None = None,
        *,
        page_size: int | None = None,
    ) -> None:
        self.client = client or MercadoLivreApiClient()
        self.page_size = min(max(int(page_size or settings.ML_API_PAGE_SIZE), 1), 50)
        self._item_cache: dict[str, dict[str, Any]] = {}

    def search(
        self,
        *,
        query_text: str = '',
        category_id: str = '',
        sort: str = '',
        max_pages: int,
        provenance: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if settings.ML_API_SITE_ID != 'MLB':
            raise MercadoLivreApiError(
                'A integração deste projeto aceita somente o site MLB.',
                status_code=None,
                endpoint='/sites/{SITE_ID}/search',
            )
        item_ids: list[str] = []
        seen_ids: set[str] = set()
        offset = 0
        provenance = dict(provenance or {})

        for _ in range(max(1, max_pages)):
            params: dict[str, str | int] = {
                'offset': offset,
                'limit': self.page_size,
            }
            if query_text.strip():
                params['q'] = query_text.strip()
            if category_id.strip():
                params['category'] = category_id.strip()
            if sort.strip():
                params['sort'] = sort.strip()

            body = self.client.get(
                f'/sites/{settings.ML_API_SITE_ID}/search',
                params=params,
            )
            results, paging, schema_error = self._validate_search_page(
                body,
                requested_offset=offset,
            )
            if schema_error:
                raise MercadoLivreApiError(
                    schema_error,
                    status_code=None,
                    endpoint='/sites/{SITE_ID}/search',
                )

            page_ids = list(results)
            for item_id in page_ids:
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    item_ids.append(item_id)

            total = paging['total']
            page_limit = paging['limit']
            next_offset = paging['offset'] + page_limit
            if not page_ids or (total and next_offset >= total):
                break
            if next_offset <= offset:
                break
            offset = next_offset

        return self._hydrate(item_ids, provenance=provenance, query_text=query_text, category_id=category_id)

    def _validate_search_page(
        self,
        body: Any,
        *,
        requested_offset: int,
    ) -> tuple[list[str], dict[str, int], str]:
        try:
            if not isinstance(body, dict):
                return [], {}, 'Busca do Mercado Livre retornou formato inválido.'
            results = body.get('results')
            paging = body.get('paging')
            if not isinstance(results, list):
                return [], {}, 'Busca do Mercado Livre retornou results inválido.'
            if not isinstance(paging, dict):
                return [], {}, 'Busca do Mercado Livre retornou paging inválido.'
            required_fields = ('total', 'offset', 'limit')
            if any(field not in paging for field in required_fields):
                return [], {}, 'Busca do Mercado Livre retornou paging incompleto.'
            if any(
                isinstance(paging[field], bool)
                or not isinstance(paging[field], int)
                or paging[field] < 0
                for field in required_fields
            ):
                return [], {}, 'Busca do Mercado Livre retornou paging inválido.'
            total = paging['total']
            offset = paging['offset']
            page_limit = paging['limit']
            if offset != requested_offset or page_limit < 1 or page_limit > self.page_size:
                return [], {}, 'Busca do Mercado Livre retornou paginação inválida.'
            if offset > total or len(results) != min(total - offset, page_limit):
                return [], {}, 'Busca do Mercado Livre retornou cardinalidade inconsistente.'
            if any(
                not isinstance(item, str)
                or item != item.strip()
                or not ML_ITEM_ID_RE.fullmatch(item)
                for item in results
            ):
                return [], {}, 'Busca do Mercado Livre retornou item inválido.'
            if len(set(results)) != len(results):
                return [], {}, 'Busca do Mercado Livre retornou IDs duplicados.'
            return results, {
                'total': total,
                'offset': offset,
                'limit': page_limit,
            }, ''
        except Exception:  # noqa: BLE001 - resposta externa fail-closed
            return [], {}, 'Busca do Mercado Livre retornou schema inválido.'

    def search_many(
        self,
        requests_to_run: Iterable[dict[str, Any]],
        *,
        max_pages: int,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for request in requests_to_run:
            candidates = self.search(max_pages=max_pages, **request)
            for candidate in candidates:
                item_id = str(candidate.get('id') or '')
                if not item_id:
                    continue
                current = merged.get(item_id)
                if current is None:
                    merged[item_id] = candidate
                    continue
                current_provenance = current.setdefault('_search_provenance', {})
                incoming_provenance = candidate.get('_search_provenance') or {}
                for key, value in incoming_provenance.items():
                    if value and not current_provenance.get(key):
                        current_provenance[key] = value
                if not current.get('_category_id') and candidate.get('_category_id'):
                    current['_category_id'] = candidate['_category_id']
                if not current.get('_category_code') and candidate.get('_category_code'):
                    current['_category_code'] = candidate['_category_code']
                if not current.get('_category_hint') and candidate.get('_category_hint'):
                    current['_category_hint'] = candidate['_category_hint']
        return list(merged.values())

    def _hydrate(
        self,
        item_ids: list[str],
        *,
        provenance: dict[str, str],
        query_text: str,
        category_id: str,
    ) -> list[dict[str, Any]]:
        missing_ids = [item_id for item_id in item_ids if item_id not in self._item_cache]
        entries = self.client.get_items(missing_ids) if missing_ids else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            code = self._as_int(entry.get('status_code', entry.get('code')))
            body = entry.get('body')
            entry_id = str(entry.get('id') or '').strip()
            if code == 404:
                if entry_id:
                    self._item_cache[entry_id] = {'id': entry_id, '_api_error': 404}
                continue
            if code and code >= 400:
                raise MercadoLivreApiError(
                    f'Multiget de item rejeitado (HTTP {code}).',
                    status_code=code,
                    endpoint='/items/bulk',
                    auth_error=code in (401, 403),
                )
            if not isinstance(body, dict):
                continue
            item = dict(body)
            item_id = str(item.get('id') or entry_id).strip()
            if not item_id:
                continue
            item['id'] = item_id
            self._item_cache[item_id] = item

        hydrated: list[dict[str, Any]] = []
        for item_id in item_ids:
            cached = self._item_cache.get(item_id)
            if cached is None:
                continue
            item = dict(cached)
            if item.get('_api_error'):
                item['_search_provenance'] = dict(provenance)
                item['_search_query'] = query_text
                item['_category_id'] = category_id
                item['_category_code'] = provenance.get('category_code', '')
                item['_collection_source'] = 'mercadolivre_api'
                hydrated.append(item)
                continue
            item['_search_provenance'] = dict(provenance)
            item['_search_query'] = query_text
            item['_category_id'] = category_id
            category_code = provenance.get('category_code', '')
            item['_category_code'] = category_code
            if str(provenance.get('trust_hint', 'true')).lower() not in {'0', 'false', 'no'}:
                item['_category_hint'] = category_code
            else:
                item['_category_hint'] = ''
            item['_collection_source'] = 'mercadolivre_api'
            hydrated.append(item)
        return hydrated

    @staticmethod
    def _extract_item_id(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get('id')
        return str(value or '').strip()

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
