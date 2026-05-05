from django.core.management.base import BaseCommand

from apps.marketplaces.models import Marketplace


class Command(BaseCommand):
    help = 'Cria ou atualiza os marketplaces iniciais do descontos.bot.'

    def handle(self, *args, **options):
        marketplaces = [
            {
                'name': 'Mercado Livre',
                'code': 'mercadolivre',
                'base_url': 'https://www.mercadolivre.com.br',
                'is_active': True,
                'affiliate_enabled': False,
            },
            {
                'name': 'Amazon',
                'code': 'amazon',
                'base_url': 'https://www.amazon.com.br',
                'is_active': True,
                'affiliate_enabled': False,
            },
        ]

        for data in marketplaces:
            marketplace, created = Marketplace.objects.update_or_create(
                code=data['code'],
                defaults=data,
            )
            action = 'criado' if created else 'atualizado'
            self.stdout.write(
                self.style.SUCCESS(
                    f'Marketplace {marketplace.name} {action}.',
                ),
            )
