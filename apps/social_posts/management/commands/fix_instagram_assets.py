"""
Management command: fix_instagram_assets

Verifica e repara assets do Instagram que estejam com caminhos ausentes,
antigos (media/instagram_posts/) ou inválidos.

Uso:
    python3 manage.py fix_instagram_assets
    python3 manage.py fix_instagram_assets --dry-run
    python3 manage.py fix_instagram_assets --format story
"""

import json
import logging
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.social_posts.models import InstagramPost
from apps.social_posts.services.image_renderer import (
    render_story_asset,
    render_feed_asset,
)

logger = logging.getLogger(__name__)

OLD_INSTA_DIR = 'instagram_posts'
FRESHNESS_HOURS = 36


def _is_old_path(path: str) -> bool:
    return OLD_INSTA_DIR in path


def _file_exists(asset_paths: list[str]) -> bool:
    for p in asset_paths:
        if not Path(p).exists():
            return False
    return bool(asset_paths)


def _regenerate_for_post(post: InstagramPost) -> InstagramPost:
    """Regenera asset de um post, forcando nova renderizacao."""
    if post.format == InstagramPost.Format.STORY:
        asset = render_story_asset(post.primary_offer, link=post.sticker_target_url)
    elif post.format == InstagramPost.Format.FEED:
        asset = render_feed_asset(post.primary_offer)
    else:
        # Carrossel não regeneramos individualmente porque depende de N ofertas
        return post

    post.asset_paths = [asset.path]
    post.save(update_fields=['asset_paths'])
    return post


class Command(BaseCommand):
    help = 'Verifica e repara assets do Instagram com caminhos ausentes ou antigos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas reporta, não altera nada.',
        )
        parser.add_argument(
            '--format',
            choices=['story', 'feed', 'carousel'],
            help='Filtrar por formato específico.',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        fmt_filter = options.get('format')

        posts = InstagramPost.objects.select_related('primary_offer__marketplace').all()
        if fmt_filter:
            posts = posts.filter(format=fmt_filter)

        total = posts.count()
        old_paths = 0
        missing_files = 0
        regenerated = 0
        errors = 0

        self.stdout.write(f'Verificando {total} posts Instagram...')

        for post in posts:
            raw = json.loads(post.asset_paths) if isinstance(post.asset_paths, str) else post.asset_paths
            paths = list(raw) if raw else []

            has_old = any(_is_old_path(p) for p in paths)
            has_missing = not _file_exists(paths)

            if has_old:
                old_paths += 1

            if has_old or has_missing:
                missing_files += 1

                if not dry_run:
                    if post.format == InstagramPost.Format.CAROUSEL:
                        self.stdout.write(
                            f'  SKIP carrossel #{post.id} ({post.primary_offer}): '
                            f'regen individual não suportado.',
                        )
                        continue

                    # Freshness check — pular ofertas velhas
                    created = post.primary_offer.created_at
                    if created and (timezone.now() - created) > timedelta(hours=FRESHNESS_HOURS):
                        self.stdout.write(
                            self.style.WARNING(
                                f'  SKIP #{post.id}: offer {post.primary_offer_id} '
                                f'older than {FRESHNESS_HOURS}h threshold ({created.date()}).',
                            ),
                        )
                        continue

                    try:
                        new_post = _regenerate_for_post(post)
                        new_paths = json.loads(new_post.asset_paths) if isinstance(new_post.asset_paths, str) else new_post.asset_paths
                        if _file_exists(new_paths):
                            regenerated += 1
                            self.stdout.write(
                                f'  OK #{post.id} ({post.format}): {new_paths[0][:80]}',
                            )
                        else:
                            errors += 1
                            self.stdout.write(
                                self.style.ERROR(
                                    f'  FAIL #{post.id}: regen não produziu arquivo válido.',
                                ),
                            )
                    except Exception as exc:
                        errors += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f'  ERROR #{post.id}: {exc}',
                            ),
                        )

        self.stdout.write()
        summary = (
            f'Total: {total} | Caminhos antigos: {old_paths} | '
            f'Assets ausentes: {missing_files} | '
            f'Regenerados: {regenerated} | Erros: {errors}'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING(f'[DRY-RUN] {summary}'))
            self.stdout.write('Nenhuma alteração foi feita.')
        else:
            self.stdout.write(
                self.style.SUCCESS(summary) if errors == 0 else self.style.WARNING(summary),
            )

            if regenerated > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'{regenerated} asset(ns) foram regenerados.'),
                )
            if errors > 0:
                self.stdout.write(
                    self.style.ERROR(f'{errors} erro(s) — verifique os logs acima.'),
                )
