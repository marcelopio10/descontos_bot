from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.curation.services.blacklist_updates import rollback_curation_blacklist_term


class Command(BaseCommand):
    help = 'Rollback de termo automático de blacklist da curadoria IA.'

    def add_arguments(self, parser):
        parser.add_argument('--term', default='', help='Termo normalizado/display para rollback.')
        parser.add_argument('--id', dest='term_id', type=int, default=None, help='ID do CurationBlacklistTerm ativo.')
        parser.add_argument('--reason', default='', help='Motivo do rollback humano.')

    def handle(self, *args, **options):
        term = options['term'].strip()
        term_id = options['term_id']
        if not term and term_id is None:
            raise CommandError('Informe --term ou --id.')
        try:
            result = rollback_curation_blacklist_term(
                term=term or None,
                term_id=term_id,
                reason=options['reason'],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f'rolled_back={result.term.normalized_term} removed_from_setting={result.removed_from_setting}'
        )
