import traceback

from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    publish_story,
    record_failure,
)


class Command(BaseCommand):
    help = 'Publica um InstagramPost no Instagram via Composio (apenas formato story por enquanto).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--post-id',
            type=int,
            required=True,
            help='ID do InstagramPost a publicar.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Roda fluxo sem chamar API (gera JPEG e mostra payload).',
        )

    def handle(self, *args, **options):
        post_id = options['post_id']
        try:
            post = InstagramPost.objects.get(pk=post_id)
        except InstagramPost.DoesNotExist:
            raise CommandError(f'InstagramPost #{post_id} não encontrado.')

        if post.format != InstagramPost.Format.STORY:
            raise CommandError(
                f'Apenas formato STORY suportado. Post #{post_id} é {post.format}.'
            )

        try:
            result = publish_story(post, dry_run=options['dry_run'])
        except ComposioPublishError as exc:
            error = f'[{exc.stage}] {exc}'
            self.stderr.write(self.style.ERROR(error))
            if not options['dry_run']:
                record_failure(post, error)
            raise CommandError(error)
        except Exception as exc:
            error = f'Erro inesperado: {exc}\n{traceback.format_exc()}'
            self.stderr.write(self.style.ERROR(error))
            if not options['dry_run']:
                record_failure(post, error)
            raise CommandError('Falha — detalhes acima.')

        mode = 'DRY-RUN' if options['dry_run'] else 'PUBLICADO'
        self.stdout.write(self.style.SUCCESS(
            f'{mode} | post #{post_id} | container={result.container_id} '
            f'media={result.media_id}'
        ))
