import hashlib
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone
from PIL import Image

from apps.social_posts.models import InstagramPost


log = logging.getLogger(__name__)

CREATE_ACTION = 'INSTAGRAM_POST_IG_USER_MEDIA'
PUBLISH_ACTION = 'INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH'
PROFILE_ACTION = 'INSTAGRAM_GET_USER_INFO'
MEDIA_ACTION = 'INSTAGRAM_GET_IG_MEDIA'

JPEG_QUALITY = 95
MAX_IMAGE_DIMENSION = 1920
PUBLISH_STATES = {
    'not_started',
    'started',
    'confirmed',
    'unknown',
    'failed',
}


class ComposioPublishError(RuntimeError):
    def __init__(self, message: str, stage: str = '', payload: dict | None = None):
        super().__init__(message)
        self.stage = stage
        self.payload = payload or {}


class ComposioPublishUnknownError(ComposioPublishError):
    """The external provider may have performed an effect that we could not verify."""


@dataclass(frozen=True)
class PublishResult:
    container_id: str
    media_id: str
    asset_path: str
    permalink: str = ''


def publish_story(post: InstagramPost, *, dry_run: bool = False) -> PublishResult:
    if post.format != InstagramPost.Format.STORY:
        raise ComposioPublishError(
            f'Apenas formato STORY suportado. Recebido: {post.format}',
            stage='precheck',
        )
    return publish_post(post, dry_run=dry_run)


def publish_post(post: InstagramPost, *, dry_run: bool = False) -> PublishResult:
    """Publish one Feed or Story and confirm the resulting Instagram media.

    The connected account is always selected explicitly. The local database is only
    marked as posted after `INSTAGRAM_GET_IG_MEDIA` confirms the returned media.
    """
    if post.format not in (InstagramPost.Format.FEED, InstagramPost.Format.STORY):
        raise ComposioPublishError(
            f'Apenas formatos FEED e STORY suportados. Recebido: {post.format}',
            stage='precheck',
        )
    if post.publication_receipt.get('status') == 'PUBLICADA' and post.instagram_permalink:
        return PublishResult(
            container_id=post.instagram_container_id,
            media_id=post.instagram_media_id,
            asset_path=_resolve_asset_path(post).as_posix(),
            permalink=post.instagram_permalink,
        )
    if post.status not in (
        InstagramPost.Status.DRAFT,
        InstagramPost.Status.READY,
        InstagramPost.Status.AWAITING_POST,
    ):
        raise ComposioPublishError(
            f'Post #{post.id} já está em status "{post.status}".',
            stage='precheck',
        )

    asset_path = _resolve_asset_path(post)
    source_hash = _sha256(asset_path)
    effective_dry_run = dry_run or settings.INSTAGRAM_PUBLISH_DRY_RUN
    ig_user_id = str(getattr(settings, 'INSTAGRAM_USER_ID', '') or '')

    if effective_dry_run:
        jpeg_path = _make_temp_jpeg(asset_path)
        try:
            payload = _build_create_payload(post, ig_user_id or 'dry-run-user', jpeg_path)
            log.info(
                'Instagram dry-run post_id=%s format=%s payload_keys=%s',
                post.id,
                post.format,
                sorted(payload),
            )
        finally:
            jpeg_path.unlink(missing_ok=True)
        return PublishResult(
            container_id='dry-run-container',
            media_id='dry-run-media',
            asset_path=str(asset_path),
        )

    profile = _preflight_account()
    ig_user_id = str(profile.get('id') or '')
    if not ig_user_id:
        raise ComposioPublishError('Instagram account ID não retornado no preflight.', 'preflight')

    jpeg_path = _make_temp_jpeg(asset_path)
    create_started = False
    try:
        _mark_started(post, source_hash)
        create_payload = _build_create_payload(post, ig_user_id, jpeg_path)
        create_started = True
        container = _composio_execute(CREATE_ACTION, create_payload)
        container_id = _extract_id(container, stage='create')
        post.instagram_container_id = container_id
        post.save(update_fields=['instagram_container_id', 'updated_at'])

        published = _composio_execute(
            PUBLISH_ACTION,
            {
                'ig_user_id': ig_user_id,
                'creation_id': container_id,
                'max_wait_seconds': 60,
                'poll_interval_seconds': 3,
            },
        )
        media_id = _extract_id(published, stage='publish')
        media = _composio_execute(
            MEDIA_ACTION,
            {
                'ig_media_id': media_id,
                'fields': 'id,caption,media_type,permalink,timestamp,username',
            },
        )
        permalink = _verify_media(media, media_id, post.caption)
        _mark_confirmed(
            post,
            source_hash=source_hash,
            container_id=container_id,
            media_id=media_id,
            permalink=permalink,
            media=media,
        )
        return PublishResult(
            container_id=container_id,
            media_id=media_id,
            asset_path=str(asset_path),
            permalink=permalink,
        )
    except ComposioPublishUnknownError as exc:
        _mark_unknown(post, str(exc))
        raise
    except ComposioPublishError:
        if create_started and post.publish_state == 'started':
            _mark_unknown(post, 'Falha após iniciar operação externa; reconciliação necessária.')
        raise
    except Exception as exc:  # noqa: BLE001
        if create_started:
            _mark_unknown(post, f'Falha inesperada após iniciar operação externa: {exc}')
            raise ComposioPublishUnknownError(
                'Resultado externo desconhecido; reconcilie antes de repetir.',
                stage='unknown',
            ) from exc
        raise ComposioPublishError(str(exc), stage='local') from exc
    finally:
        jpeg_path.unlink(missing_ok=True)


def preflight_account() -> dict[str, Any]:
    """Run the live account identity check without creating or publishing media."""
    return _preflight_account()


def record_failure(post: InstagramPost, error: str) -> None:
    post.published_error = error[:4000]
    post.publish_state = 'failed'
    post.status = InstagramPost.Status.REJECTED
    post.save(update_fields=['published_error', 'publish_state', 'status', 'updated_at'])


def record_unknown_failure(post: InstagramPost, error: str) -> None:
    post.published_error = error[:4000]
    post.publish_state = 'unknown'
    post.save(update_fields=['published_error', 'publish_state', 'updated_at'])


def _preflight_account() -> dict[str, Any]:
    account_id = getattr(settings, 'COMPOSIO_INSTAGRAM_ACCOUNT_ID', '')
    expected_username = getattr(settings, 'INSTAGRAM_EXPECTED_USERNAME', '')
    project_name = getattr(settings, 'COMPOSIO_PROJECT_NAME', '')
    user_id = getattr(settings, 'COMPOSIO_USER_ID', '')
    missing = [
        name for name, value in (
            ('COMPOSIO_PROJECT_NAME', project_name),
            ('COMPOSIO_USER_ID', user_id),
            ('COMPOSIO_INSTAGRAM_ACCOUNT_ID', account_id),
            ('INSTAGRAM_EXPECTED_USERNAME', expected_username),
        ) if not value
    ]
    if missing:
        raise ComposioPublishError(
            f'Configuração Composio incompleta: {", ".join(missing)}',
            stage='config',
        )
    profile = _composio_execute(PROFILE_ACTION, {})
    username = profile.get('username')
    if username != expected_username:
        raise ComposioPublishError(
            f'Conta Instagram divergente: esperado @{expected_username}, retornado @{username}.',
            stage='preflight',
        )
    return profile


def _composio_execute(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a Composio action through the SDK with explicit account pinning."""
    account_id = getattr(settings, 'COMPOSIO_INSTAGRAM_ACCOUNT_ID', '')
    user_id = getattr(settings, 'COMPOSIO_USER_ID', '')
    project_name = getattr(settings, 'COMPOSIO_PROJECT_NAME', '')
    if not account_id or not user_id or not project_name:
        raise ComposioPublishError('Configuração Composio ausente.', stage='config')
    try:
        from composio import Composio
    except ImportError as exc:
        raise ComposioPublishError(
            'Dependência composio não instalada; execute pip install -r requirements.txt.',
            stage='dependency',
        ) from exc

    try:
        result = Composio(
            dangerously_allow_auto_upload_download_files=True,
            file_upload_dirs=[str(settings.BASE_DIR / 'media')],
        ).tools.execute(
            action,
            arguments=payload,
            connected_account_id=account_id,
            user_id=user_id,
            version=getattr(settings, 'COMPOSIO_INSTAGRAM_TOOLKIT_VERSION', '20260708_00'),
        )
    except Exception as exc:  # noqa: BLE001
        raise ComposioPublishError(f'Composio {action} falhou: {exc}', stage=action) from exc
    if not isinstance(result, dict):
        try:
            result = dict(result)
        except (TypeError, ValueError) as exc:
            raise ComposioPublishError(
                f'Composio {action} retornou formato inválido.',
                stage=action,
            ) from exc
    if 'successful' in result:
        if not result.get('successful') or result.get('error'):
            raise ComposioPublishError(
                f'Composio {action} retornou falha.',
                stage=action,
                payload=result,
            )
        data = result.get('data')
        if isinstance(data, dict):
            return data
    return result


def _build_create_payload(post: InstagramPost, ig_user_id: str, jpeg_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'ig_user_id': ig_user_id,
        'image_file': str(jpeg_path),
    }
    if post.format == InstagramPost.Format.STORY:
        payload['media_type'] = 'STORIES'
    if post.caption:
        payload['caption'] = post.caption[:2200]
    return payload


def _resolve_asset_path(post: InstagramPost) -> Path:
    if not post.asset_paths:
        raise ComposioPublishError(f'Post #{post.id} sem asset_paths.', stage='precheck')
    path = Path(post.asset_paths[0])
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    if not path.exists():
        raise ComposioPublishError(f'Asset não existe no disco: {path}', stage='precheck')
    return path


def _make_temp_jpeg(source: Path) -> Path:
    upload_dir = Path(settings.MEDIA_ROOT) / 'instagram' / 'composio_uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(suffix='.jpg', dir=upload_dir, delete=False)
    target = Path(handle.name)
    handle.close()
    with Image.open(source) as original:
        rgb = original.convert('RGB')
        rgb.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
        rgb.save(target, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _mark_started(post: InstagramPost, source_hash: str) -> None:
    post.publish_attempts += 1
    post.publish_state = 'started'
    post.published_error = ''
    post.publication_receipt = {
        'status': 'INICIADA',
        'asset_sha256': source_hash,
        'started_at': timezone.now().isoformat(),
    }
    post.save(update_fields=['publish_attempts', 'publish_state', 'published_error', 'publication_receipt', 'updated_at'])


def _mark_unknown(post: InstagramPost, error: str) -> None:
    post.publish_state = 'unknown'
    post.published_error = error[:4000]
    post.save(update_fields=['publish_state', 'published_error', 'updated_at'])


def _mark_confirmed(
    post: InstagramPost,
    *,
    source_hash: str,
    container_id: str,
    media_id: str,
    permalink: str,
    media: dict[str, Any],
) -> None:
    now = timezone.now()
    post.instagram_container_id = container_id
    post.instagram_media_id = media_id
    post.instagram_permalink = permalink
    post.publish_state = 'confirmed'
    post.published_error = ''
    post.posted_at = now
    post.status = InstagramPost.Status.POSTED
    post.publication_receipt = {
        'status': 'PUBLICADA',
        'asset_sha256': source_hash,
        'instagram_username': media.get('username'),
        'instagram_media_id': media_id,
        'permalink': permalink,
        'caption_verified': media.get('caption') == post.caption,
        'media_type': media.get('media_type'),
        'timestamp': media.get('timestamp'),
        'confirmed_at': now.isoformat(),
    }
    post.save(update_fields=[
        'instagram_container_id',
        'instagram_media_id',
        'instagram_permalink',
        'publish_state',
        'published_error',
        'posted_at',
        'status',
        'publication_receipt',
        'updated_at',
    ])


def _verify_media(media: dict[str, Any], media_id: str, caption: str) -> str:
    permalink = media.get('permalink')
    expected_username = getattr(settings, 'INSTAGRAM_EXPECTED_USERNAME', '')
    if (
        str(media.get('id') or media_id) != media_id
        or media.get('username') != expected_username
        or not isinstance(permalink, str)
        or not permalink.startswith('https://')
        or media.get('caption') != caption
    ):
        raise ComposioPublishUnknownError(
            'Mídia publicada não pôde ser reconciliada com a conta/caption esperadas.',
            stage='reconcile',
            payload=media,
        )
    return permalink


def _extract_id(result: dict[str, Any], *, stage: str) -> str:
    data = result.get('data') or result
    media_id = data.get('id') if isinstance(data, dict) else None
    if not media_id:
        raise ComposioPublishUnknownError(
            f'{stage}: resposta sem campo id.',
            stage=stage,
            payload=result,
        )
    return str(media_id)
