from django.core.management.base import BaseCommand, CommandError

from apps.social_posts.services.bio_link_publisher import publish_bio_links


class Command(BaseCommand):
    help = 'Exporta links rastreados para uso manual na bio do Instagram.'

    def add_arguments(self, parser):
        parser.add_argument('--output', required=True, help='Caminho de saída do JSON de links.')
        parser.add_argument('--count', type=int, default=5, help='Quantidade de links exportados.')

    def handle(self, *args, **options):
        try:
            result = publish_bio_links(
                output_path=options['output'],
                count=options['count'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Links da bio gerados em {result.output_path} com {result.items_count} itens.',
            ),
        )
        self.stdout.write(f'Arquivo para copiar links: {result.output_path}')
