"""Coleta ofertas da Shopee Affiliate API, normaliza e (opcionalmente) persiste.

Seguro por padrão: sem `--save` é dry-run (não grava nada). `--save` exige
SHOPEE_AFFILIATE_ENABLED=true. Não publica em nenhum canal — apenas coleta e
normaliza, deixando curadoria/publicação para os fluxos existentes.

Exemplos:
    # Keyword direta (modo original)
    python3 manage.py collect_shopee_offers --keyword "fone bluetooth" --limit 5

    # Categorias (como Amazon e Mercado Livre)
    python3 manage.py collect_shopee_offers --categories --save
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateError
from apps.marketplaces.services.shopee_collectors import ProductOfferCollector
from apps.marketplaces.services.shopee_normalizer import normalize_shopee_item
from apps.offers.services.normalizer import OfferNormalizationError
from apps.offers.services.repository import save_normalized_offer
from apps.scraping.services.adapters import build_adapter
from apps.curation.services.settings import get_integer_setting


CATEGORY_SCRAPING_FLAG = 'category_scraping_enabled'


class Command(BaseCommand):
    help = 'Coleta ofertas da Shopee Affiliate API (dry-run por padrão).'

    def add_arguments(self, parser):
        parser.add_argument('--keyword', type=str, default=None)
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--page', type=int, default=1)
        parser.add_argument(
            '--categories',
            action='store_true',
            help=(
                'Busca por categorias configuradas em category_targets.py '
                '(keywords por categoria, igual Amazon/ML). '
                'Ignora --keyword quando usado.'
            ),
        )
        parser.add_argument(
            '--category',
            type=str,
            default=None,
            help='Filtra por código de categoria específica (ex: tecnologia_cotidiana).',
        )
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
        use_categories = bool(options['categories']) or bool(options.get('category'))
        category_filter = options.get('category')

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

        # Decide entre busca por categorias ou keyword direta
        items: list[dict] = []
        category_hint_map: dict[str, str] = {}

        if use_categories:
            items, category_hint_map = self._collect_by_categories(category_filter)
        else:
            collector = ProductOfferCollector()
            try:
                items = collector.fetch(
                    keyword=options['keyword'],
                    limit=options['limit'],
                    page=options['page'],
                )
            except ShopeeAffiliateError as exc:
                raise CommandError(f'Falha na coleta Shopee: {exc}') from exc

        # Normalização e persistência
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
        source = 'categories' if use_categories else 'keyword'
        self.stdout.write(
            self.style.SUCCESS(
                f'[{mode}] source={source} recebidas={received} normalizadas={normalized_count} '
                f'criadas={created_count} atualizadas={updated_count} '
                f'rejeitadas={rejected_count}',
            ),
        )
        if not persist:
            self.stdout.write('Dry-run: nenhuma oferta foi gravada.')

    def _collect_by_categories(
        self, category_filter: str | None
    ) -> tuple[list[dict], dict[str, str]]:
        """Coleta via ScraperAdapter com category_targets (igual Amazon/ML)."""
        from scrapers.category_targets import flatten_urls

        adapter = build_adapter('shopee')
        targets = flatten_urls('shopee')

        if category_filter:
            targets = [t for t in targets if t.category_code == category_filter]
            if not targets:
                categories = sorted(set(t.category_code for t in flatten_urls('shopee')))
                raise CommandError(
                    f'Categoria "{category_filter}" não encontrada. '
                    f'Disponíveis: {", ".join(categories)}',
                )

        self.stdout.write(
            f'Coletando Shopee por categorias: {len(targets)} keywords em '
            f'{len(set(t.category_code for t in targets))} categorias'
        )

        scraper_targets = [
            (t.category_code, t.label, t.url, t.trust_hint) for t in targets
        ]

        try:
            offers = adapter.scraper.scrape_categories(scraper_targets)
        except ShopeeAffiliateError as exc:
            raise CommandError(f'Falha na coleta Shopee por categorias: {exc}') from exc

        # Extrai os raw_payload e injeta category_hint para o classifier
        items: list[dict] = []
        for offer in offers:
            item = offer.get('raw_payload', {})
            cat_hint = offer.get('category_hint', '')
            if cat_hint and item:
                # Garante que o dict é mutável
                if not isinstance(item, dict):
                    item = dict(item) if hasattr(item, 'items') else {}
                item['category_hint'] = cat_hint
            items.append(item)

        self.stdout.write(
            f'  Categorias: ofertas={len(offers)} '
            f'blocked={adapter.scraper.blocked} pages={adapter.scraper.pages_scraped}',
        )

        return items, {}
