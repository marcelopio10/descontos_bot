from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.curation.services.hermes_runner import HermesProfileRunner
from apps.distribution.models import SocialChannel

from apps.coupons.models import CouponCandidate, CouponRun
from apps.coupons.services.collector import collect_marketplaces
from apps.coupons.services.curation import CouponFakeRunner, curate_candidates
from apps.coupons.services.observer_editorial import build_coupon_editorial_pattern
from apps.coupons.services.publishing import publish_coupon
from apps.coupons.services.report import write_coupon_report
from apps.coupons.services.validation import validate_candidate


class Command(BaseCommand):
    help = 'Descobre, valida, cura e publica cupons diariamente.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--runner', choices=['real', 'fake'], default='real')
        parser.add_argument('--report-dir', default='')

    def handle(self, *args, **options):
        today = timezone.localdate()
        run_key = f'coupons-{today.isoformat()}'
        run, created = CouponRun.objects.get_or_create(
            run_key=run_key,
            defaults={'started_at': timezone.now(), 'status': 'running'},
        )
        if not created and run.status == 'completed':
            self.stdout.write(f'Execução {run_key} já concluída; nada duplicado.')
            return
        rejected = []
        try:
            raw_candidates, sources = collect_marketplaces()
            run.sources_json = sources
            run.candidates_found = len(raw_candidates)
            run.observer_pattern_json = build_coupon_editorial_pattern()
            run.save(update_fields=['sources_json', 'candidates_found', 'observer_pattern_json', 'updated_at'])
            valid = []
            seen = set()
            with transaction.atomic():
                for raw in raw_candidates:
                    result = validate_candidate(raw, seen)
                    if not result.accepted:
                        raw['reason'] = result.reason
                        rejected.append(raw)
                        continue
                    seen.add(raw['candidate_hash'])
                    candidate, _ = CouponCandidate.objects.get_or_create(
                        run=run, candidate_hash=raw['candidate_hash'], defaults=raw,
                    )
                    candidate.validation_status = 'valid'
                    candidate.save(update_fields=['validation_status', 'updated_at'])
                    valid.append(candidate)
            channel = SocialChannel.objects.filter(code='whatsapp_principal').first() or SocialChannel.objects.filter(channel_type__startswith='whatsapp', is_enabled=True).first()
            if channel is None:
                raise RuntimeError('nenhum canal WhatsApp habilitado')
            runner = HermesProfileRunner(profile_name='descontos-bot') if options['runner'] == 'real' else CouponFakeRunner()
            selected = curate_candidates(run, valid, channel, runner=runner, observer_pattern=run.observer_pattern_json)
            publication_rows, posts = [], []
            channels = list(SocialChannel.objects.filter(is_enabled=True, code__in=['whatsapp_principal', 'telegram_main']))
            if not options['dry_run']:
                for candidate in selected:
                    for target in channels:
                        delivery = publish_coupon(candidate, target)
                        publication_rows.append({'channel': target.code, 'status': delivery.status, 'error': delivery.error_message})
            for candidate in selected:
                posts.append({'marketplace': candidate.marketplace, 'post': candidate.decision.whatsapp_post, 'published_url': candidate.affiliate_url or candidate.destination_url})
            run.finished_at = timezone.now()
            run.save(update_fields=['finished_at', 'updated_at'])
            report_root = Path(options['report_dir'] or os.environ.get('COUPON_REPORT_DIR', str(Path('site') / 'descontos.bot' / 'cupons')))
            report_path = report_root / f'{today.isoformat()}.html'
            write_coupon_report(run, path=report_path, rejected=rejected, posts=posts, publication_rows=publication_rows)
            self.stdout.write(self.style.SUCCESS(f'Cupons: {len(selected)} selecionados; relatório: {report_path}'))
        except Exception as exc:
            run.status = 'failed'
            run.errors_json = [*run.errors_json, f'{type(exc).__name__}: {exc}']
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'errors_json', 'finished_at', 'updated_at'])
            self.stderr.write(self.style.ERROR(str(exc)))
