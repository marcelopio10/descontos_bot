from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.curation.models import CurationRun

# O timeout do runner Hermes é 450s (Sprint 5). Toda falha dentro do processo já
# chama `_fail_run` e fecha a run; o que sobra em `running` é run cujo processo
# morreu no meio — restart do run-bot.service, desligamento do notebook, SIGKILL.
# 60 min dá folga larga sobre o timeout e ainda assim não deixa lixo de estado
# acumulando: eram 27 runs presas em 30 dias antes deste comando existir.
DEFAULT_OLDER_THAN_MINUTES = 60

REAP_MESSAGE = (
    'Run encerrada pelo reaper: ficou em `running` por mais de {minutes} min sem '
    'desfecho. Causa típica é o processo ter morrido no meio (restart de serviço '
    'ou desligamento), não falha da curadoria em si.'
)


class Command(BaseCommand):
    help = 'Marca como `failed` as CurationRun presas em `running` além do limite.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Só lista o que seria encerrado.')
        parser.add_argument(
            '--older-than-minutes',
            type=int,
            default=DEFAULT_OLDER_THAN_MINUTES,
            help=f'Idade mínima em `running` para encerrar. Default: {DEFAULT_OLDER_THAN_MINUTES}.',
        )

    def handle(self, *args, **options):
        minutes = options['older_than_minutes']
        dry_run = options['dry_run']
        cutoff = timezone.now() - timedelta(minutes=minutes)

        stuck = CurationRun.objects.filter(
            status=CurationRun.Status.RUNNING,
            created_at__lt=cutoff,
        ).order_by('created_at')

        total = stuck.count()
        if not total:
            self.stdout.write(f'reap_stuck_curation_runs older_than_minutes={minutes} stuck=0')
            return

        for run in stuck:
            age_min = int((timezone.now() - run.created_at).total_seconds() // 60)
            channel = getattr(run.channel, 'code', run.channel_id)
            self.stdout.write(f'  run={run.id} canal={channel} idade={age_min}min candidatas={run.candidate_count}')

        if dry_run:
            self.stdout.write(f'reap_stuck_curation_runs dry_run older_than_minutes={minutes} would_reap={total}')
            return

        # `update` em vez de save() por run: é escrita curta e o SQLite aqui é
        # WAL compartilhado com o run_bot — quanto menos tempo de transação,
        # menor a chance de disputar o lock.
        reaped = stuck.update(
            status=CurationRun.Status.FAILED,
            error_message=REAP_MESSAGE.format(minutes=minutes),
            updated_at=timezone.now(),
        )
        self.stdout.write(f'reap_stuck_curation_runs older_than_minutes={minutes} reaped={reaped}')
