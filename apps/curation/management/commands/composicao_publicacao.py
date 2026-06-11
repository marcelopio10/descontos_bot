from collections import Counter, defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.distribution.models import Delivery
from apps.offers.models import Category


class Command(BaseCommand):
    help = (
        'Sprint 6 — relatório da composição real das publicações por categoria '
        'e por canal, comparando cota configurada vs. realizado.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Janela em dias (default: 1).',
        )
        parser.add_argument(
            '--channel',
            type=str,
            default=None,
            help='Filtra por código de canal social (opcional).',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])

        qs = (
            Delivery.objects.select_related('offer__category', 'social_channel')
            .filter(
                delivery_status=Delivery.DeliveryStatus.SENT,
                sent_at__gte=cutoff,
            )
        )
        if options['channel']:
            qs = qs.filter(social_channel__code=options['channel'])

        per_channel: dict[str, Counter] = defaultdict(Counter)
        totals: Counter = Counter()
        global_total = 0

        for delivery in qs.iterator():
            channel = delivery.social_channel.code if delivery.social_channel else '-'
            cat_code = (
                delivery.offer.category.code
                if delivery.offer.category_id else 'sem_categoria'
            )
            per_channel[channel][cat_code] += 1
            totals[cat_code] += 1
            global_total += 1

        quotas = {
            c.code: float(c.exposure_quota_pct or 0)
            for c in Category.objects.filter(is_active=True)
            if c.exposure_quota_pct is not None
        }

        suffix = f'(últimos {options["days"]}d'
        if options['channel']:
            suffix += f', canal={options["channel"]}'
        suffix += ')'

        self.stdout.write(f'Composição global {suffix}: {global_total} envios')
        self.stdout.write(
            f'{"categoria":24} {"envios":>7} {"%real":>7} {"%cota":>7}  delta'
        )
        self.stdout.write('-' * 65)
        all_codes = sorted(set(totals) | set(quotas), key=lambda c: -totals.get(c, 0))
        for code in all_codes:
            sent = totals.get(code, 0)
            real_pct = (sent / global_total * 100) if global_total else 0.0
            quota_pct = quotas.get(code)
            quota_str = f'{quota_pct:>6.1f}%' if quota_pct is not None else '   —  '
            delta = ''
            if quota_pct is not None:
                diff = real_pct - quota_pct
                signal = '+' if diff >= 0 else '-'
                delta = f'{signal}{abs(diff):.1f}pp'
            self.stdout.write(
                f'{code:24} {sent:>7} {real_pct:>6.1f}% {quota_str}  {delta}'
            )

        if not per_channel:
            return

        self.stdout.write('')
        self.stdout.write('Composição por canal:')
        for channel, counts in sorted(per_channel.items()):
            total = sum(counts.values())
            self.stdout.write(f'  {channel} ({total} envios)')
            for code, n in counts.most_common():
                pct = (n / total * 100) if total else 0.0
                self.stdout.write(f'    {code:24} {n:>5} ({pct:>5.1f}%)')
