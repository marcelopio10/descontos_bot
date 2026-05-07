from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.post_generator import generate_carousel


class Command(BaseCommand):
    help = 'Gera assets e legenda para carrossel manual no Instagram.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=5, help='Quantidade de ofertas no carrossel.')

    def handle(self, *args, **options):
        try:
            post = generate_carousel(count=options['count'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(f'Carrossel Instagram #{post.id} gerado com {len(post.asset_paths)} assets.'),
        )
        self.stdout.write('Assets:')
        for asset_path in post.asset_paths:
            self.stdout.write(f'- {asset_path}')
        self.stdout.write(f'Link principal rastreado: {post.sticker_target_url}')
        self.stdout.write('Para links individuais de bio, rode publish_bio_link.')
