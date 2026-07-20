from django.core.management.base import BaseCommand

from apps.analytics.services.observer_healthcheck import (
    DEFAULT_STALE_HOURS,
    canais_sem_entrega_recente,
    observer_esta_atrasado,
    verificar_canais_sem_entrega,
    verificar_observer_atrasado,
)


class Command(BaseCommand):
    help = (
        'Verifica a saúde do observer de WhatsApp (market intel) e dos canais de '
        'distribuição, disparando alerta ao operador via Telegram quando algo '
        'fica parado por tempo demais.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=DEFAULT_STALE_HOURS,
            help=f'Janela em horas considerada "sem atividade" (default: {DEFAULT_STALE_HOURS}).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help=(
                'Roda só as consultas, sem disparar nenhum alerta real '
                '(útil para testar o comando sem enviar mensagem ao operador).'
            ),
        )

    def handle(self, *args, **options):
        horas = options['hours']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: nenhum alerta será enviado de verdade.'))
            observer_atrasado = observer_esta_atrasado(horas)
            canais_sem_entrega = canais_sem_entrega_recente(horas)
        else:
            observer_atrasado = verificar_observer_atrasado(horas)
            canais_sem_entrega = verificar_canais_sem_entrega(horas)

        if observer_atrasado:
            self.stdout.write(
                self.style.ERROR(f'Observer sem coleta nova há mais de {horas}h.'),
            )
        else:
            self.stdout.write(self.style.SUCCESS('Observer OK: coleta recente dentro do limite.'))

        if canais_sem_entrega:
            self.stdout.write(
                self.style.ERROR(
                    f'Canais sem entrega há mais de {horas}h: {", ".join(canais_sem_entrega)}',
                ),
            )
        else:
            self.stdout.write(self.style.SUCCESS('Canais OK: todos com entrega recente.'))
