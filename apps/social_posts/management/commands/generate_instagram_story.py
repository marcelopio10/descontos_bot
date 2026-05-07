from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.post_generator import generate_story


class Command(BaseCommand):
    help = 'Gera asset e link rastreado para story manual no Instagram.'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=1, help='Ranking da oferta a usar.')

    def handle(self, *args, **options):
        try:
            post = generate_story(top=options['top'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f'Story Instagram #{post.id} gerado com {len(post.asset_paths)} asset.'),
        )
        self.stdout.write(f'Asset: {post.asset_paths[0]}')
        self.stdout.write(f'Link do sticker: {post.sticker_target_url}')
