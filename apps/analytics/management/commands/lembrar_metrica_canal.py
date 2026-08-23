"""Cobra do dono a contagem semanal de membros do canal.

Item 8 da Onda 1. O número de público não tem como ser medido sozinho: o adapter
Evolution não expõe contagem de participantes do grupo, então o dado depende de
alguém abrir o WhatsApp e contar. O que dá para automatizar é a **cobrança** — e
é isso que este comando faz.

Só o WhatsApp é acompanhado: o Telegram saiu do acompanhamento na decisão de
2026-08-23 (revisão 2.2 do diagnóstico), por não ser canal de distribuição.

    manage.py lembrar_metrica_canal                  # usado pelo timer semanal
    manage.py lembrar_metrica_canal --dry-run        # não envia alerta
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.analytics.models import FonteMetricaCanal, MetricaCanalDiaria
from apps.analytics.services.alertas import enviar_alerta_operador
from apps.distribution.models import SocialChannel

DEFAULT_CHANNEL_CODE = 'whatsapp_principal'
DEFAULT_MAX_AGE_DAYS = 8


class Command(BaseCommand):
    help = (
        'Verifica há quantos dias não existe medição verificada de membros e '
        'avisa o operador quando ela envelhece.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--canal',
            default=DEFAULT_CHANNEL_CODE,
            help=f'Code do SocialChannel (default: {DEFAULT_CHANNEL_CODE}).',
        )
        parser.add_argument(
            '--max-age-days',
            type=int,
            default=DEFAULT_MAX_AGE_DAYS,
            help=(
                'Idade máxima aceitável da última medição verificada '
                f'(default: {DEFAULT_MAX_AGE_DAYS}).'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Só imprime o diagnóstico, sem disparar alerta.',
        )

    def handle(self, *args, **options):
        canal_code = options['canal']
        canal = SocialChannel.objects.filter(code=canal_code).first()
        if canal is None:
            self.stdout.write(self.style.ERROR(f'Canal "{canal_code}" não existe.'))
            return

        ultima = (
            MetricaCanalDiaria.objects.filter(canal=canal)
            .exclude(fonte=FonteMetricaCanal.ESTIMADO)
            .order_by('-data')
            .first()
        )
        hoje = timezone.localdate()

        if ultima is None:
            mensagem = (
                f'Nenhuma medição verificada de membros para {canal.name}. '
                'Conte os participantes do grupo e registre com: '
                f'manage.py registrar_metrica_canal --canal {canal_code} '
                f'--data {hoje:%Y-%m-%d} --membros <N> --fonte informado_dono'
            )
            self._report(mensagem, options['dry_run'], nivel='erro')
            return

        idade = (hoje - ultima.data).days
        if idade > options['max_age_days']:
            mensagem = (
                f'A contagem de membros de {canal.name} está com {idade} dias '
                f'(última: {ultima.data:%d/%m/%Y}, {ultima.membros} membros). '
                'Conte e registre: '
                f'manage.py registrar_metrica_canal --canal {canal_code} '
                f'--data {hoje:%Y-%m-%d} --membros <N> --fonte informado_dono'
            )
            self._report(mensagem, options['dry_run'], nivel='aviso')
            return

        self.stdout.write(self.style.SUCCESS(
            f'{canal.name}: última medição verificada em {ultima.data:%d/%m/%Y} '
            f'({idade} dia(s), {ultima.membros} membros). Nada a cobrar.'
        ))

    def _report(self, mensagem: str, dry_run: bool, nivel: str):
        estilo = self.style.ERROR if nivel == 'erro' else self.style.WARNING
        self.stdout.write(estilo(mensagem))
        if dry_run:
            self.stdout.write('  (dry-run: alerta não enviado)')
            return
        enviar_alerta_operador(mensagem, categoria='metrica_canal_vencida')
