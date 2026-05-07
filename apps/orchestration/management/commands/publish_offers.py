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
        parser.add_argument(
            '--branch',
            default=None,
            help='Branch de destino do push. Padrão: PUBLISH_OFFERS_BRANCH ou main.',
        )

    def handle(self, *args, **options):
        result = publish_offers(
            output_path=options['output'],
            push=options['push'],
            branch=options['branch'],
        )
        if result['error']:
            raise CommandError(result['error'])

        self.stdout.write(
            self.style.SUCCESS(
                f'offers.json gerado em {result["output_path"]} com {result["offers_count"]} ofertas.',
            ),
        )
        if result['changed']:
            self.stdout.write(self.style.SUCCESS('Diff real detectado em offers.json.'))
        else:
            self.stdout.write('Sem alterações reais para publicar no repositório integrado.')

        if result['committed']:
            self.stdout.write(self.style.SUCCESS('Commit criado: chore: publish offers json'))
        if result['pushed']:
            self.stdout.write(self.style.SUCCESS('Push executado no repositório integrado.'))
