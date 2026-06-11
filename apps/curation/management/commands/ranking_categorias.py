from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.curation.services.category_weights import (
    get_all_weights,
    get_override_map,
)
from apps.curation.services.quality_score import quality_score_breakdown
from apps.offers.models import Category, Offer
from apps.offers.services.freshness import get_freshness_cutoff


class Command(BaseCommand):
    help = (
        'Lista o ranking atual de categorias: peso efetivo (override + banco), '
        'volume de ofertas ativas, score médio e distribuição por decisão.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh-only',
            action='store_true',
            help='Considera apenas ofertas dentro da janela de freshness.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limita a varredura para acelerar diagnóstico (por categoria).',
        )

    def handle(self, *args, **options):
        weights = get_all_weights()
        overrides = get_override_map()

        base_qs = Offer.objects.select_related('marketplace', 'category').filter(
            is_active=True,
        )
        if options['fresh_only']:
            base_qs = base_qs.filter(last_seen_at__gte=get_freshness_cutoff())

        active_counts = dict(
            base_qs
            .filter(category__isnull=False)
            .values_list('category__code')
            .annotate(n=Count('id'))
            .values_list('category__code', 'n')
        )

        rows = []
        for category in Category.objects.filter(is_active=True).order_by('-weight', 'name'):
            scores: list[float] = []
            decisions: dict[str, int] = {}
            qs = base_qs.filter(category=category)
            if options['limit']:
                qs = qs[: options['limit']]
            for offer in qs.iterator():
                breakdown = quality_score_breakdown(offer)
                scores.append(breakdown.score)
                decisions[breakdown.decision] = decisions.get(breakdown.decision, 0) + 1

            rows.append(
                {
                    'code': category.code,
                    'name': category.name,
                    'weight_db': category.weight,
                    'weight_effective': weights.get(category.code, category.weight),
                    'overridden': category.code in overrides,
                    'is_test_controlled': category.is_test_controlled,
                    'count_active': active_counts.get(category.code, 0),
                    'avg_score': sum(scores) / len(scores) if scores else 0.0,
                    'decisions': decisions,
                }
            )

        rows.sort(key=lambda r: (-r['weight_effective'], r['code']))

        suffix = ' (fresh-only)' if options['fresh_only'] else ''
        self.stdout.write(f'Ranking de categorias{suffix}:')
        self.stdout.write(
            f'{"code":24} {"peso_db":>7} {"peso_efetivo":>13} {"ofertas":>8} {"score_médio":>12}  decisões'
        )
        self.stdout.write('-' * 110)
        for r in rows:
            marker_override = '*' if r['overridden'] else ' '
            marker_test = 'T' if r['is_test_controlled'] else ' '
            decisions_str = ', '.join(f'{k}={v}' for k, v in sorted(r['decisions'].items())) or '-'
            self.stdout.write(
                f'{r["code"]:24} {r["weight_db"]:>7} {r["weight_effective"]:>10}{marker_override}{marker_test}  '
                f'{r["count_active"]:>8} {r["avg_score"]:>12.2f}  {decisions_str}'
            )

        if overrides:
            self.stdout.write('')
            self.stdout.write('Overrides ativos (Setting category_weights):')
            for code, value in sorted(overrides.items()):
                self.stdout.write(f'  {code:24} -> {value}')
        else:
            self.stdout.write('')
            self.stdout.write(
                'Nenhum override em Setting category_weights. Peso efetivo = Category.weight.'
            )

        self.stdout.write('')
        self.stdout.write('Legenda: * = peso sobrescrito por Setting, T = categoria de teste controlado.')
