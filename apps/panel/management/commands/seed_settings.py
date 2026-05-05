from django.core.management.base import BaseCommand

from apps.panel.models import Setting


class Command(BaseCommand):
    help = 'Cria ou atualiza configurações operacionais iniciais.'

    def handle(self, *args, **options):
        settings = [
            {
                'key': 'batch_size',
                'value': '20',
                'description': 'Limite legado de ofertas por ciclo.',
            },
            {
                'key': 'offer_limit_global',
                'value': '20',
                'description': 'Limite global de ofertas por ciclo em dry_run e envio.',
            },
            {
                'key': 'offer_limit_per_marketplace',
                'value': '10',
                'description': 'Limite de ofertas por marketplace em cada ciclo.',
            },
            {
                'key': 'cycle_min_minutes',
                'value': '90',
                'description': 'Intervalo mínimo entre ciclos contínuos.',
            },
            {
                'key': 'cycle_max_minutes',
                'value': '180',
                'description': 'Intervalo máximo entre ciclos contínuos.',
            },
            {
                'key': 'min_discount_percentage',
                'value': '20',
                'description': 'Desconto mínimo recomendado para seleção.',
            },
            {
                'key': 'allow_original_link_when_affiliate_missing',
                'value': 'true',
                'description': 'Permite link original quando afiliado não existir.',
            },
        ]

        for data in settings:
            setting, created = Setting.objects.update_or_create(
                key=data['key'],
                defaults=data,
            )
            action = 'criada' if created else 'atualizada'
            self.stdout.write(
                self.style.SUCCESS(
                    f'Configuração {setting.key} {action}.',
                ),
            )
