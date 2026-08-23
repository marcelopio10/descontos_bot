from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.models import FonteMetricaCanal, MetricaCanalDiaria
from apps.distribution.models import SocialChannel


class Command(BaseCommand):
    help = (
        'Registra (ou atualiza) a contagem agregada de membros/seguidores de '
        'um canal em uma data (Sprint 7 - Tarefa 7.3). Entrada manual '
        'periódica — LGPD: só contagem agregada, nunca dado individual.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--canal',
            required=True,
            help='Code do SocialChannel (ex.: whatsapp_principal, telegram_main).',
        )
        parser.add_argument(
            '--data',
            required=True,
            help='Data da medição, formato YYYY-MM-DD.',
        )
        parser.add_argument(
            '--membros',
            type=int,
            required=True,
            help='Contagem agregada de membros/seguidores nesta data.',
        )
        parser.add_argument(
            '--posts-publicados',
            type=int,
            default=None,
            help=(
                'Posts/stories publicados nesta data. Se omitido, o painel '
                'calcula automaticamente a partir dos envios (Delivery).'
            ),
        )
        parser.add_argument(
            '--cliques-estimados',
            type=int,
            default=None,
            help='Cliques estimados (medição indireta/manual, opcional).',
        )
        parser.add_argument(
            '--fonte',
            required=True,
            choices=[choice.value for choice in FonteMetricaCanal],
            help=(
                'De onde veio o número. `medido_api` = contado por API do canal; '
                '`informado_dono` = contado e informado pelo dono; `estimado` = '
                'palpite, fica fora da curva do painel. Obrigatório desde '
                '2026-08-23: os três registros anteriores eram estimativa gravada '
                'como medição, erradas por 12x e 143x.'
            ),
        )

    def handle(self, *args, **options):
        try:
            canal = SocialChannel.objects.get(code=options['canal'])
        except SocialChannel.DoesNotExist:
            raise CommandError(
                f'Canal "{options["canal"]}" não encontrado (SocialChannel.code).'
            )

        try:
            medicao_data = datetime.strptime(options['data'], '%Y-%m-%d').date()
        except ValueError:
            raise CommandError('--data inválida, use o formato YYYY-MM-DD.')

        metrica, created = MetricaCanalDiaria.objects.update_or_create(
            canal=canal,
            data=medicao_data,
            defaults={
                'membros': options['membros'],
                'posts_publicados': options['posts_publicados'],
                'cliques_estimados': options['cliques_estimados'],
                'fonte': options['fonte'],
            },
        )

        action = 'criada' if created else 'atualizada'
        self.stdout.write(
            self.style.SUCCESS(
                f'Métrica {action}: {metrica.canal.name} — '
                f'{metrica.data.isoformat()} — {metrica.membros} membros '
                f'({metrica.get_fonte_display()}).'
            )
        )

        if metrica.fonte == FonteMetricaCanal.ESTIMADO:
            self.stdout.write(self.style.WARNING(
                '  ! Marcada como estimativa: fica fora da curva do painel. '
                'Use --fonte informado_dono ou medido_api para um número conferido.'
            ))
