from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.post_generator import generate_story


class Command(BaseCommand):
    help = 'Gera asset e link rastreado para story manual no Instagram.'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=1, help='Ranking da oferta a usar.')

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                'Geração manual de story no Instagram está desativada. '
                'Nenhum post foi gerado. A geração automática (run_bot) segue ativa.',
            ),
        )
        return

        try:
            post = generate_story(top=options['top'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        image_path = Path(post.asset_paths[0])
        sidecar_path = image_path.with_suffix('.txt')

        self.stdout.write(
            self.style.SUCCESS(f'Story Instagram #{post.id} gerado.'),
        )
        self.stdout.write(f'Imagem: {image_path}')
        self.stdout.write(f'Link (.txt): {sidecar_path}')
        self.stdout.write(f'Link do sticker: {post.sticker_target_url}')
