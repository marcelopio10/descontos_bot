from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.curation.models import CuratedBatch, CuratedBatchItem

FetchImage = Callable[[str], bytes]

DEFAULT_MAX_DIMENSION = 1280
DEFAULT_MIN_WIDTH = 300
DEFAULT_MIN_HEIGHT = 300
DEFAULT_TIMEOUT_SECONDS = 12


class ImageProcessingError(Exception):
    pass


@dataclass(frozen=True)
class ImageProcessingResult:
    processed: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class CleanupResult:
    scanned: int
    deleted: int
    would_delete: int


def process_selected_batch_images(
    batch: CuratedBatch,
    *,
    media_root: Path | str,
    fetcher: FetchImage | None = None,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    min_width: int = DEFAULT_MIN_WIDTH,
    min_height: int = DEFAULT_MIN_HEIGHT,
) -> ImageProcessingResult:
    """Download/process images only for selected batch items.

    Failures are persisted per decision/item and never raise to the caller.
    """
    media_root = Path(media_root)
    fetcher = fetcher or fetch_image_bytes
    processed = failed = skipped = 0

    items = batch.items.select_related('decision', 'offer').order_by('position')
    for item in items:
        decision = item.decision
        if decision.ai_classification == 'improper':
            _mark_replacement(item, status='blocked', reason='improper_decision')
            failed += 1
            continue
        image_url = (item.final_image_url or item.offer.image_url or '').strip()
        if not image_url:
            _mark_replacement(item, status='needs_replacement', reason='missing_image_url')
            failed += 1
            continue
        try:
            raw = fetcher(image_url)
            image = _load_image(raw)
            width, height = image.size
            if width < min_width or height < min_height:
                _mark_replacement(
                    item,
                    status='needs_replacement',
                    reason='image_too_small',
                    width=width,
                    height=height,
                )
                failed += 1
                continue
            image = _resize_if_needed(image, max_dimension=max_dimension)
            path = _local_image_path(media_root, item)
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, format='JPEG', quality=88, optimize=True)
            saved_width, saved_height = image.size
            item.local_image_path = str(path)
            item.image_width = saved_width
            item.image_height = saved_height
            item.image_mime_type = 'image/jpeg'
            item.final_image_url = ''
            item.save(update_fields=['local_image_path', 'image_width', 'image_height', 'image_mime_type', 'final_image_url', 'updated_at'])
            _mark_processed(item, image_url=image_url, width=saved_width, height=saved_height)
            processed += 1
        except Exception as exc:
            _mark_replacement(item, status='needs_replacement', reason='download_or_processing_failed', error=str(exc)[:500])
            failed += 1

    return ImageProcessingResult(processed=processed, failed=failed, skipped=skipped)


def fetch_image_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS, headers={'User-Agent': 'descontos.bot-curation/1.0'})
    if response.status_code >= 400:
        raise ImageProcessingError(f'HTTP {response.status_code}')
    content_type = response.headers.get('content-type', '')
    if content_type and not content_type.lower().startswith('image/'):
        raise ImageProcessingError(f'content-type inválido: {content_type}')
    return response.content


def cleanup_curation_media(
    *,
    media_root: Path | str,
    older_than_hours: int = 36,
    dry_run: bool = False,
) -> CleanupResult:
    root = Path(media_root) / 'curation'
    if not root.exists():
        return CleanupResult(scanned=0, deleted=0, would_delete=0)

    cutoff = timezone.now().timestamp() - older_than_hours * 3600
    scanned = deleted = would_delete = 0
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        scanned += 1
        if path.stat().st_mtime >= cutoff:
            continue
        if dry_run:
            would_delete += 1
        else:
            path.unlink(missing_ok=True)
            deleted += 1
    _remove_empty_dirs(root)
    return CleanupResult(scanned=scanned, deleted=deleted, would_delete=would_delete)


def _load_image(raw: bytes) -> Image.Image:
    try:
        from io import BytesIO
        image = Image.open(BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        elif image.mode == 'L':
            image = image.convert('RGB')
        else:
            image = image.copy()
        return image
    except UnidentifiedImageError as exc:
        raise ImageProcessingError('imagem inválida') from exc


def _resize_if_needed(image: Image.Image, *, max_dimension: int) -> Image.Image:
    width, height = image.size
    biggest = max(width, height)
    if biggest <= max_dimension:
        return image
    scale = max_dimension / biggest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _local_image_path(media_root: Path, item: CuratedBatchItem) -> Path:
    return media_root / 'curation' / f'run-{item.batch.run_id}' / f'batch-{item.batch_id}' / f'offer-{item.offer_id}.jpg'


def _mark_processed(item: CuratedBatchItem, *, image_url: str, width: int, height: int) -> None:
    decision = item.decision
    analysis = dict(decision.image_analysis_json or {})
    analysis.update(
        {
            'status': 'processed',
            'decision': analysis.get('decision') or 'approved',
            'source_url_present': bool(image_url),
            'local_image_path': item.local_image_path,
            'width': width,
            'height': height,
            'mime_type': 'image/jpeg',
            'multimodal_ready': True,
            'processed_at': timezone.now().isoformat(),
        }
    )
    decision.image_analysis_json = analysis
    decision.image_score = decision.image_score or 100
    decision.save(update_fields=['image_analysis_json', 'image_score', 'updated_at'])


def _mark_replacement(
    item: CuratedBatchItem,
    *,
    status: str,
    reason: str,
    error: str = '',
    width: int | None = None,
    height: int | None = None,
) -> None:
    item.local_image_path = ''
    item.image_width = width
    item.image_height = height
    item.image_mime_type = ''
    item.save(update_fields=['local_image_path', 'image_width', 'image_height', 'image_mime_type', 'updated_at'])
    decision = item.decision
    analysis = dict(decision.image_analysis_json or {})
    analysis.update(
        {
            'status': status,
            'reason': reason,
            'error': error,
            'width': width,
            'height': height,
            'multimodal_ready': False,
            'processed_at': timezone.now().isoformat(),
        }
    )
    decision.image_analysis_json = analysis
    decision.save(update_fields=['image_analysis_json', 'updated_at'])


def _remove_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
