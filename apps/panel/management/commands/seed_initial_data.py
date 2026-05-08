from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Executa todos os seeds iniciais do MVP local.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--target',
            default='descontos.bot - Homologação',
            help='Nome exato do grupo WhatsApp usado pelo canal de homologação.',
        )

    def handle(self, *args, **options):
        call_command('seed_marketplaces')
        call_command('seed_channels', target=options['target'])
        call_command('seed_settings')
        self.stdout.write(
            self.style.SUCCESS('Dados iniciais do descontos.bot configurados.'),
        )
