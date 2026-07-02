from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.curation.services.image_processing import cleanup_curation_media


class Command(BaseCommand):
    help = 'Remove imagens antigas de curadoria IA em media/curation.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Só mostra contagem; não remove arquivos.')
        parser.add_argument('--older-than-hours', type=int, default=36, help='Idade mínima para expurgo. Default: 36h.')
        parser.add_argument('--media-root', default=str(getattr(settings, 'MEDIA_ROOT', 'media')), help='Raiz de mídia local.')

    def handle(self, *args, **options):
        result = cleanup_curation_media(
            media_root=Path(options['media_root']),
            older_than_hours=options['older_than_hours'],
            dry_run=options['dry_run'],
        )
        if options['dry_run']:
            self.stdout.write(
                f'cleanup_curation_media dry_run scanned={result.scanned} would_delete={result.would_delete}'
            )
        else:
            self.stdout.write(
                f'cleanup_curation_media scanned={result.scanned} deleted={result.deleted}'
            )
