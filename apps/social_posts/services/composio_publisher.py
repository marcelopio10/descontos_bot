import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from PIL import Image

from apps.social_posts.models import InstagramPost


log = logging.getLogger(__name__)

CREATE_ACTION = 'INSTAGRAM_POST_IG_USER_MEDIA'
PUBLISH_ACTION = 'INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH'

JPEG_QUALITY = 90
MAX_STORY_DIMENSION = 1920  # Instagram story 1080x1920


class ComposioPublishError(RuntimeError):
    def __init__(self, message: str, stage: str = '', payload: dict | None = None):
        super().__init__(message)
        self.stage = stage
        self.payload = payload or {}


@dataclass(frozen=True)
class PublishResult:
    container_id: str
    media_id: str
    asset_path: str


def publish_story(post: InstagramPost, *, dry_run: bool = False) -> PublishResult:
    """Compatibilidade: publica somente InstagramPost formato Story via Composio."""
    if post.format != InstagramPost.Format.STORY:
        raise ComposioPublishError(
            f'Apenas formato STORY suportado. Recebido: {post.format}',
            stage='precheck',
        )
    return publish_post(post, dry_run=dry_run)


def publish_post(post: InstagramPost, *, dry_run: bool = False) -> PublishResult:
    """Publica um InstagramPost de feed ou story via Composio CLI.

    Fluxo:
    1. Pega o primeiro asset_path do post (PNG gerado pelo image_renderer)
    2. Converte pra JPEG temporário (formato aceito pelo Instagram Graph)
    3. INSTAGRAM_POST_IG_USER_MEDIA cria o container
       - feed: image_file + caption
       - story: media_type=STORIES + image_file + caption
    4. INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH publica o container
    5. Atualiza InstagramPost: status=posted, posted_at, instagram_media_id

    Observação: a API do Instagram publica o Story, mas não cria Link Sticker.
    O link fica registrado em sticker_target_url para auditoria/fallback manual.
    """
    if post.format not in (InstagramPost.Format.FEED, InstagramPost.Format.STORY):
        raise ComposioPublishError(
            f'Apenas formatos FEED e STORY suportados. Recebido: {post.format}',
            stage='precheck',
        )
    if post.status not in (
        InstagramPost.Status.READY,
        InstagramPost.Status.DRAFT,
        InstagramPost.Status.AWAITING_POST,
    ):
        raise ComposioPublishError(
            f'Post #{post.id} já está em status "{post.status}".',
            stage='precheck',
        )

    asset_path = _resolve_asset_path(post)
    ig_user_id = settings.INSTAGRAM_USER_ID
    if not ig_user_id:
        raise ComposioPublishError(
            'IG_USER_ID não configurado no settings.',
            stage='config',
        )

    effective_dry_run = dry_run or settings.INSTAGRAM_PUBLISH_DRY_RUN

    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        jpeg_path = Path(tmp.name)

    try:
        _convert_to_jpeg(asset_path, jpeg_path)

        create_payload = _build_create_payload(post, ig_user_id, jpeg_path)

        if effective_dry_run:
            log.info('DRY-RUN: container payload=%s', create_payload)
            return PublishResult(
                container_id='dry-run-container',
                media_id='dry-run-media',
                asset_path=str(jpeg_path),
            )

        create_result = _composio_execute(CREATE_ACTION, create_payload)
        container_id = _extract_id(create_result, stage='create')

        time.sleep(2)

        publish_payload = {
            'ig_user_id': ig_user_id,
            'creation_id': container_id,
            'max_wait_seconds': 60,
            'poll_interval_seconds': 3,
        }
        publish_result = _composio_execute(PUBLISH_ACTION, publish_payload)
        media_id = _extract_id(publish_result, stage='publish')

    finally:
        try:
            jpeg_path.unlink(missing_ok=True)
        except OSError:
            pass

    post.instagram_media_id = media_id
    post.status = InstagramPost.Status.POSTED
    post.posted_at = timezone.now()
    post.published_error = ''
    post.save(
        update_fields=[
            'instagram_media_id',
            'status',
            'posted_at',
            'published_error',
            'updated_at',
        ]
    )

    return PublishResult(
        container_id=container_id,
        media_id=media_id,
        asset_path=str(asset_path),
    )


def record_failure(post: InstagramPost, error: str) -> None:
    """Marca post como rejeitado com o erro completo gravado."""
    post.published_error = error[:4000]
    post.status = InstagramPost.Status.REJECTED
    post.save(update_fields=['published_error', 'status', 'updated_at'])


def _resolve_asset_path(post: InstagramPost) -> Path:
    if not post.asset_paths:
        raise ComposioPublishError(
            f'Post #{post.id} sem asset_paths.',
            stage='precheck',
        )
    raw = post.asset_paths[0]
    path = Path(raw)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    if not path.exists():
        raise ComposioPublishError(
            f'Asset não existe no disco: {path}',
            stage='precheck',
        )
    return path


def _convert_to_jpeg(source: Path, target: Path) -> None:
    with Image.open(source) as img:
        rgb = img.convert('RGB')
        rgb.thumbnail(
            (MAX_STORY_DIMENSION, MAX_STORY_DIMENSION),
            Image.LANCZOS,
        )
        rgb.save(target, format='JPEG', quality=JPEG_QUALITY, optimize=True)


def _build_create_payload(post: InstagramPost, ig_user_id: str, jpeg_path: Path) -> dict:
    payload = {
        'ig_user_id': ig_user_id,
        'image_file': str(jpeg_path),
    }
    if post.format == InstagramPost.Format.STORY:
        payload['media_type'] = 'STORIES'
    caption = str(post.caption or '')
    if caption:
        payload['caption'] = caption[:2200]
    return payload


def _composio_execute(action: str, payload: dict) -> dict:
    cmd = [
        settings.COMPOSIO_BIN,
        'execute',
        action,
        '-d',
        json.dumps(payload),
    ]

    log.info('Composio execute: %s payload=%s', action, payload)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ComposioPublishError(
            f'Binário Composio não encontrado em {settings.COMPOSIO_BIN}: {exc}',
            stage='subprocess',
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposioPublishError(
            f'Timeout no {action} (>180s).',
            stage=action,
        ) from exc

    if proc.returncode != 0:
        raise ComposioPublishError(
            f'{action} retornou exit={proc.returncode}: {proc.stderr or proc.stdout}',
            stage=action,
        )

    data = _parse_composio_output(proc.stdout)
    if not data.get('successful'):
        err = data.get('error') or data.get('data', {}).get('composio_execution_message')
        raise ComposioPublishError(
            f'{action} falhou: {err}',
            stage=action,
            payload=data,
        )
    return data


def _parse_composio_output(stdout: str) -> dict:
    """Composio CLI mistura logs com JSON final. Pega o último bloco JSON válido."""
    candidates = []
    buffer = []
    depth = 0
    for line in stdout.splitlines():
        stripped = line.strip()
        if not buffer and not stripped.startswith('{'):
            continue
        buffer.append(line)
        depth += stripped.count('{') - stripped.count('}')
        if buffer and depth <= 0:
            candidates.append('\n'.join(buffer))
            buffer = []
            depth = 0
    for candidate in reversed(candidates):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ComposioPublishError(
            f'Resposta Composio não é JSON válido: {stdout[:500]}',
            stage='parse',
        ) from exc


def _extract_id(result: dict, *, stage: str) -> str:
    data = result.get('data') or {}
    media_id = data.get('id') or data.get('response_data', {}).get('id')
    if not media_id:
        raise ComposioPublishError(
            f'{stage}: resposta sem campo id. data={data}',
            stage=stage,
            payload=result,
        )
    return str(media_id)
