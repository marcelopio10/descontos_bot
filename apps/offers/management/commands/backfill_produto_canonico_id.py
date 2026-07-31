from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.offers.models import Offer
from apps.offers.services.normalizer import build_produto_canonico_id


log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500


class Command(BaseCommand):
    """Preenche `Offer.produto_canonico_id` para registros existentes (Sprint 5 / achado P8).

    O campo é aditivo (adicionado via migration 0008_offer_produto_canonico_id) e
    todo registro novo já é preenchido no fluxo normal de scraping (ver
    apps.offers.services.repository.save_normalized_offer). Este comando é um
    backfill único para os registros que já existiam antes do campo existir.

    Rodado como comando separado (em vez de RunPython dentro da própria
    migration de schema) para permitir --dry-run e execução em lotes com
    progresso visível, já que este ambiente roda contra um banco de produção
    real com um processo de longa duração ativo (run_bot) — mais seguro do
    que embutir uma migração de dados pesada dentro do `migrate`.
    """

    help = 'Backfill de Offer.produto_canonico_id para ofertas já existentes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Calcula e reporta quantos registros mudariam, sem salvar nada.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help='Quantidade de registros por bulk_update.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        if batch_size < 1:
            batch_size = DEFAULT_BATCH_SIZE

        total = Offer.objects.count()
        self.stdout.write(f'Total de ofertas no banco: {total}')

        to_update: list[Offer] = []
        examined = 0
        would_change = 0
        changed = 0

        queryset = Offer.objects.only(
            'id', 'marketplace_id', 'asin', 'external_id', 'produto_canonico_id', 'marketplace__code',
        ).select_related('marketplace').iterator(chunk_size=batch_size)

        for offer in queryset:
            examined += 1
            marketplace_code = offer.marketplace.code if offer.marketplace_id else ''
            new_value = build_produto_canonico_id(marketplace_code, offer.asin, offer.external_id)
            if new_value == offer.produto_canonico_id:
                continue
            would_change += 1
            if dry_run:
                continue
            offer.produto_canonico_id = new_value
            to_update.append(offer)
            if len(to_update) >= batch_size:
                changed += self._flush(to_update)
                to_update = []

        if not dry_run and to_update:
            changed += self._flush(to_update)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[dry-run] examinadas={examined}; mudariam={would_change}; nada foi salvo.',
                ),
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Backfill concluído: examinadas={examined}; atualizadas={changed}.',
                ),
            )
        log.info(
            'backfill_produto_canonico_id concluído dry_run=%s examinadas=%s atualizadas_ou_mudariam=%s',
            dry_run, examined, would_change if dry_run else changed,
        )

    @transaction.atomic
    def _flush(self, offers: list[Offer]) -> int:
        Offer.objects.bulk_update(offers, ['produto_canonico_id'])
        return len(offers)
