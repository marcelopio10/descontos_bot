import traceback

from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    ComposioPublishUnknownError,
    preflight_account,
    publish_post,
    record_failure,
    record_unknown_failure,
)


class Command(BaseCommand):
    help = 'Publica um InstagramPost no Instagram via Composio (feed ou story).'

    def add_arguments(self, parser):
        parser.add_argument('--post-id', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--confirm-production',
            action='store_true',
            help='Autoriza uma publicação real individual.',
        )

    def handle(self, *args, **options):
        post_id = options['post_id']
        try:
            post = InstagramPost.objects.get(pk=post_id)
        except InstagramPost.DoesNotExist as exc:
            raise CommandError(f'InstagramPost #{post_id} não encontrado.') from exc

        if not options['dry_run'] and not options['confirm_production']:
            raise CommandError(
                'Publicação real bloqueada. Use --dry-run ou --confirm-production '
                'para autorizar um único post.'
            )
        if post.format not in (InstagramPost.Format.FEED, InstagramPost.Format.STORY):
            raise CommandError(
                f'Apenas formatos FEED e STORY suportados. Post #{post_id} é {post.format}.'
            )

        try:
            result = publish_post(post, dry_run=options['dry_run'])
        except ComposioPublishUnknownError as exc:
            error = f'[{exc.stage}] {exc}'
            record_unknown_failure(post, error)
            self.stderr.write(self.style.ERROR(error))
            raise CommandError('Resultado externo desconhecido; reconcilie antes de repetir.') from exc
        except ComposioPublishError as exc:
            error = f'[{exc.stage}] {exc}'
            self.stderr.write(self.style.ERROR(error))
            if not options['dry_run']:
                if post.publish_state == 'unknown':
                    record_unknown_failure(post, error)
                else:
                    record_failure(post, error)
            raise CommandError(error) from exc
        except Exception as exc:  # noqa: BLE001
            error = f'Erro inesperado: {exc}\n{traceback.format_exc()}'
            self.stderr.write(self.style.ERROR(error))
            if not options['dry_run']:
                record_unknown_failure(post, error)
            raise CommandError('Falha — detalhes acima.') from exc

        mode = 'DRY-RUN' if options['dry_run'] else 'PUBLICADO'
        self.stdout.write(self.style.SUCCESS(
            f'{mode} | post #{post_id} | container={result.container_id} '
            f'media={result.media_id} permalink={result.permalink or "n/a"}'
        ))
