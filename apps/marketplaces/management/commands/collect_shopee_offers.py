"""Coleta ofertas da Shopee Affiliate API, normaliza e (opcionalmente) persiste.

Seguro por padrão: sem `--save` é dry-run (não grava nada). `--save` exige
SHOPEE_AFFILIATE_ENABLED=true. Não publica em nenhum canal — apenas coleta e
normaliza, deixando curadoria/publicação para os fluxos existentes.

Exemplos:
    python3 manage.py collect_shopee_offers --keyword "fone bluetooth" --limit 5 --dry-run
    python3 manage.py collect_shopee_offers --keyword "casa" --limit 50 --save
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateError
from apps.marketplaces.services.shopee_collectors import ProductOfferCollector
from apps.marketplaces.services.shopee_normalizer import normalize_shopee_item
from apps.offers.services.normalizer import OfferNormalizationError
from apps.offers.services.repository import save_normalized_offer


class Command(BaseCommand):
    help = 'Coleta ofertas da Shopee Affiliate API (dry-run por padrão).'

    def add_arguments(self, parser):
        parser.add_argument('--keyword', type=str, default=None)
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--page', type=int, default=1)
        parser.add_argument(
            '--save',
            action='store_true',
            help='Persiste as ofertas. Exige SHOPEE_AFFILIATE_ENABLED=true. Sem isto, é dry-run.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Explicita o modo dry-run (default quando --save ausente).',
        )

    def handle(self, *args, **options):
        persist = bool(options['save'])

        if persist and not settings.SHOPEE_AFFILIATE_ENABLED:
            raise CommandError(
                'SHOPEE_AFFILIATE_ENABLED=false — persistência bloqueada. '
                'Use --dry-run ou habilite o conector para salvar.',
            )

        marketplace = Marketplace.objects.filter(code='shopee').first()
        if marketplace is None:
            raise CommandError(
                'Marketplace "shopee" não encontrado. Rode: python3 manage.py seed_marketplaces',
            )

        collector = ProductOfferCollector()
        try:
            items = collector.fetch(
                keyword=options['keyword'],
                limit=options['limit'],
                page=options['page'],
            )
        except ShopeeAffiliateError as exc:
            raise CommandError(f'Falha na coleta Shopee: {exc}') from exc

        received = len(items)
        normalized_count = created_count = updated_count = rejected_count = 0

        for item in items:
            try:
                normalized = normalize_shopee_item(marketplace, item)
            except OfferNormalizationError as exc:
                rejected_count += 1
                self.stderr.write(self.style.WARNING(f'Rejeitada: {exc}'))
                continue

            normalized_count += 1

            if not persist:
                continue

            _offer, created = save_normalized_offer(normalized)
            if created:
                created_count += 1
            else:
                updated_count += 1

        mode = 'SAVE' if persist else 'DRY-RUN'
        self.stdout.write(
            self.style.SUCCESS(
                f'[{mode}] recebidas={received} normalizadas={normalized_count} '
                f'criadas={created_count} atualizadas={updated_count} '
                f'rejeitadas={rejected_count}',
            ),
        )
        if not persist:
            self.stdout.write('Dry-run: nenhuma oferta foi gravada.')
