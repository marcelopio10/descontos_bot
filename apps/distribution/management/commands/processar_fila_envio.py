from django.core.management.base import BaseCommand

from apps.distribution.services import fila_envio


class Command(BaseCommand):
    help = (
        'Consome a fila de reenvio de Delivery (status=failed) elegíveis: '
        'tenta reenviar respeitando backoff exponencial e move para '
        'dead_letter após esgotar as tentativas (Sprint 3 - Tarefa 3.1).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista as Delivery elegíveis e o que seria tentado, sem enviar nada de verdade.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de Delivery processadas nesta execução.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        if dry_run:
            self.stdout.write(self.style.WARNING('dry-run ativo: nenhum reenvio real será feito.'))

        summary = fila_envio.process_queue(limit=limit, dry_run=dry_run)

        if not summary.outcomes:
            self.stdout.write('Nenhuma Delivery elegível para retry no momento (0 elegíveis).')
            return

        self.stdout.write(f'{len(summary.outcomes)} Delivery elegível(is) processada(s).')
        self.stdout.write('-' * 78)
        for outcome in summary.outcomes:
            self.stdout.write(
                f'  delivery_id={outcome.delivery_id:<6} offer_id={outcome.offer_id:<6} '
                f'canal={outcome.channel_code:<28} status={outcome.status:<24} '
                f'{outcome.detail}',
            )

        self.stdout.write('-' * 78)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'Seriam tentadas: {summary.would_retry}. Nenhum envio real ocorreu.'),
            )
            return

        self.stdout.write(self.style.SUCCESS(f'Reenviadas com sucesso: {summary.sent}'))
        self.stdout.write(
            self.style.WARNING(f'Aguardando próximo backoff (falharam de novo): {summary.retry_scheduled}'),
        )
        self.stdout.write(
            self.style.ERROR(f'Esgotadas / dead-letter: {summary.dead_lettered}')
            if summary.dead_lettered
            else f'Esgotadas / dead-letter: {summary.dead_lettered}',
        )
        self.stdout.write(f'Puladas neste ciclo (sessão indisponível/externo/canal não suportado): {summary.skipped}')
