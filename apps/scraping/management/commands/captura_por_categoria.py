from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.offers.models import Offer


class Command(BaseCommand):
    help = (
        'Sprint 5 — mostra distribuição de ofertas capturadas por categoria '
        'e por estratégia (genérico vs scraper segmentado), olhando o source da classificação.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Janela de comparação em horas (default: 24).',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options['hours'])

        qs = (
            Offer.objects.select_related('marketplace', 'category')
            .filter(is_active=True, last_seen_at__gte=cutoff)
        )

        per_mk_cat = Counter()
        per_source = Counter()
        per_mk_source = Counter()

        for offer in qs.iterator():
            mk = offer.marketplace.code if offer.marketplace_id else '-'
            cat = offer.category.code if offer.category_id else '-'
            src = offer.category_source or '-'
            per_mk_cat[(mk, cat)] += 1
            per_source[src] += 1
            per_mk_source[(mk, src)] += 1

        suffix = f'(últimas {options["hours"]}h)'
        self.stdout.write(f'Distribuição por marketplace × categoria {suffix}:')
        self.stdout.write(f'{"marketplace":15} {"categoria":24} {"ofertas":>8}')
        self.stdout.write('-' * 55)
        for (mk, cat), n in sorted(per_mk_cat.items(), key=lambda kv: (kv[0][0], -kv[1])):
            self.stdout.write(f'{mk:15} {cat:24} {n:>8}')

        self.stdout.write('')
        self.stdout.write(f'Distribuição por origem da classificação {suffix}:')
        for src, n in per_source.most_common():
            self.stdout.write(f'  {src:30} {n}')

        self.stdout.write('')
        self.stdout.write(f'Marketplace × origem da classificação {suffix}:')
        for (mk, src), n in sorted(per_mk_source.items(), key=lambda kv: (kv[0][0], -kv[1])):
            self.stdout.write(f'  {mk:15} {src:30} {n}')

        self.stdout.write('')
        self.stdout.write(
            'Hint hint:scraper_target = oferta veio do scraper segmentado (Sprint 5).'
        )
        self.stdout.write(
            'Hint hint:source_label = oferta veio com label do scraper genérico (Sprint 1).'
        )
        self.stdout.write(
            'Hint keyword:title = classificada pelo dicionário do classifier.'
        )
        self.stdout.write(
            'Hint fallback:outros = nenhuma regra casou.'
        )
