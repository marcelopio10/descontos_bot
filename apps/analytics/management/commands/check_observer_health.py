from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.observer_healthcheck import (
    DEFAULT_STALE_HOURS,
    canais_sem_entrega_recente,
    observer_esta_atrasado,
    verificar_canais_sem_entrega,
    verificar_observer_atrasado,
)
from apps.distribution.models import SocialChannel


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
            '--delivery-hours',
            type=int,
            default=None,
            help='Limiar de distribuição independente do limiar do observer.',
        )
        parser.add_argument(
            '--channel',
            default=None,
            help='Monitora somente este canal habilitado; padrão: todos.',
        )
        parser.add_argument(
            '--active-delivery-hours',
            action='store_true',
            help='Desconta a janela de silêncio do limiar de distribuição.',
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
        delivery_hours = options['delivery_hours']
        if delivery_hours is None:
            delivery_hours = horas
        channel_code = options['channel']
        if horas < 1 or delivery_hours < 1:
            raise CommandError('Os limiares devem ser maiores que zero.')
        if channel_code and not SocialChannel.objects.filter(
            code=channel_code, is_enabled=True,
        ).exists():
            raise CommandError('Canal inexistente ou desabilitado.')
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: nenhum alerta será enviado de verdade.'))
            observer_atrasado = observer_esta_atrasado(horas)
            canais_sem_entrega = canais_sem_entrega_recente(
                delivery_hours, channel_code=channel_code,
                active_hours=options['active_delivery_hours'],
            )
        else:
            observer_atrasado = verificar_observer_atrasado(horas)
            canais_sem_entrega = verificar_canais_sem_entrega(
                delivery_hours, channel_code=channel_code,
                active_hours=options['active_delivery_hours'],
            )

        if observer_atrasado:
            self.stdout.write(
                self.style.ERROR(f'Observer sem coleta nova há mais de {horas}h.'),
            )
        else:
            self.stdout.write(self.style.SUCCESS('Observer OK: coleta recente dentro do limite.'))

        if canais_sem_entrega:
            self.stdout.write(
                self.style.ERROR(
                    f'Canais sem entrega há mais de {delivery_hours}h: {", ".join(canais_sem_entrega)}',
                ),
            )
        else:
            self.stdout.write(self.style.SUCCESS('Canais OK: todos com entrega recente.'))
