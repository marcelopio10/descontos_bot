from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.post_generator import generate_feed_post


class Command(BaseCommand):
    help = 'Gera asset e legenda para post manual no feed do Instagram.'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=1, help='Ranking da oferta a usar.')

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                'Geração manual de post no Instagram está desativada. '
                'Nenhum post foi gerado. A geração automática (run_bot) segue ativa.',
            ),
        )
        return

        try:
            post = generate_feed_post(top=options['top'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f'Post Instagram #{post.id} gerado com {len(post.asset_paths)} asset.'),
        )
        self.stdout.write(f'Asset: {post.asset_paths[0]}')
        self.stdout.write(f'Link para bio: {post.sticker_target_url}')
