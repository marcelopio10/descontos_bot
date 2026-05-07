from django.core.management.base import BaseCommand, CommandError

from apps.offers.services.site_publisher import publish_offers


class Command(BaseCommand):
    help = 'Gera o offers.json para o site público.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default=None,
            help='Caminho de saída do offers.json. Padrão: data/exports/offers.json.',
        )
        parser.add_argument(
            '--push',
            action='store_true',
            help='Copia offers.json para site/, commita e faz push se houver diff.',
        )

    def handle(self, *args, **options):
        try:
            result = publish_offers(
                output_path=options['output'],
                push=options['push'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'offers.json gerado em {result.output_path} com {result.offers_count} ofertas.',
            ),
        )
        if result.pushed:
            if result.committed:
                self.stdout.write(self.style.SUCCESS('offers.json publicado no repositório integrado.'))
            else:
                self.stdout.write('Sem alterações para publicar no repositório integrado.')
