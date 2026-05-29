import json
import logging
from datetime import datetime
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.analytics.models import ClickEvent
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


log = logging.getLogger(__name__)
KV_EVENTS_KEY = 'clicks:events'
PAGE_SIZE = 100


class Command(BaseCommand):
    help = 'Busca eventos de clique do Vercel KV e persiste no banco local.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Exibe os eventos sem persistir.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Remove eventos processados do KV após importação.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de eventos a processar nesta execução.',
        )

    def handle(self, *args, **options):
        kv_url = getattr(settings, 'VERCEL_KV_REST_API_URL', '')
        kv_token = getattr(settings, 'VERCEL_KV_REST_API_TOKEN', '')

        if not kv_url or not kv_token:
            raise CommandError(
                'VERCEL_KV_REST_API_URL e VERCEL_KV_REST_API_TOKEN '
                'devem estar definidos no .env.',
            )

        dry_run = options['dry_run']
        limit = options['limit']
        clear_after = options['clear']

        events = self._fetch_events(kv_url, kv_token, limit)
        if not events:
            self.stdout.write('Nenhum evento pendente no KV.')
            return

        self.stdout.write(f'Eventos recebidos do KV: {len(events)}')
        created, skipped = self._process_events(events, dry_run=dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f'Importação concluída: criados={created}, ignorados={skipped}.',
            ),
        )

        if not dry_run and clear_after and created > 0:
            self._clear_kv(kv_url, kv_token, len(events))

    def _fetch_events(self, kv_url: str, kv_token: str, limit: int | None):
        lrange_url = urljoin(kv_url.rstrip('/') + '/', f'lrange/{KV_EVENTS_KEY}/0/-1')
        headers = {'Authorization': f'Bearer {kv_token}'}

        try:
            response = requests.get(lrange_url, headers=headers, timeout=15)
            response.raise_for_status()
            raw = response.json().get('result', [])
        except requests.RequestException as exc:
            raise CommandError(f'Falha ao acessar Vercel KV: {exc}') from exc

        events = []
        for item in raw:
            try:
                events.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                log.warning('Item KV inválido ignorado: %s', item)
                continue

        if limit and limit > 0:
            events = events[:limit]

        return events

    def _process_events(self, events: list[dict], dry_run: bool) -> tuple[int, int]:
        offers_by_slug = self._build_offer_index(events)
        channels_by_type = self._build_channel_index()

        created = 0
        skipped = 0

        for event in events:
            slug = event.get('slug', '')
            offer = offers_by_slug.get(slug)
            if not offer:
                skipped += 1
                log.warning('Oferta não encontrada para slug=%s', slug)
                continue

            clicked_at = self._parse_clicked_at(event.get('clicked_at', ''))
            channel = channels_by_type.get(event.get('utm_source', ''))

            if dry_run:
                self.stdout.write(
                    f'[dry-run] slug={slug} '
                    f'source={event.get("utm_source")} '
                    f'campaign={event.get("utm_campaign")} '
                    f'at={clicked_at}',
                )
                created += 1
                continue

            with transaction.atomic():
                _, was_created = ClickEvent.objects.get_or_create(
                    offer=offer,
                    social_channel=channel,
                    utm_source=event.get('utm_source', ''),
                    utm_medium=event.get('utm_medium', ''),
                    utm_campaign=event.get('utm_campaign', ''),
                    utm_content=event.get('utm_content', ''),
                    clicked_at=clicked_at,
                    user_agent=event.get('user_agent', ''),
                    ip_hash=event.get('ip_hash', ''),
                )
                if was_created:
                    created += 1
                else:
                    skipped += 1

        return created, skipped

    def _build_offer_index(self, events: list[dict]) -> dict[str, Offer]:
        slugs = {e.get('slug', '') for e in events if e.get('slug')}
        offers = Offer.objects.filter(slug__in=slugs).only('id', 'slug', 'title')
        return {o.slug: o for o in offers}

    def _build_channel_index(self) -> dict[str, SocialChannel | None]:
        channels = SocialChannel.objects.filter(is_enabled=True).only(
            'id', 'code', 'channel_type',
        )
        index: dict[str, SocialChannel | None] = {}
        for ch in channels:
            if ch.channel_type not in index:
                index[ch.channel_type] = ch
        return index

    def _parse_clicked_at(self, raw: str):
        if not raw:
            return timezone.now()
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return timezone.now()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt

    def _clear_kv(self, kv_url: str, kv_token: str, count: int):
        ltrim_url = urljoin(
            kv_url.rstrip('/') + '/',
            f'ltrim/{KV_EVENTS_KEY}/0/{count - 1}',
        )
        headers = {'Authorization': f'Bearer {kv_token}'}
        try:
            requests.post(ltrim_url, headers=headers, timeout=10)
            self.stdout.write(f'KV limpo: {count} eventos removidos.')
        except requests.RequestException as exc:
            self.stdout.write(
                self.style.WARNING(f'Aviso: falha ao limpar KV: {exc}'),
            )
