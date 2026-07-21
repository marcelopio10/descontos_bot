from django.core.management.base import BaseCommand

from apps.scraping.services.ml_cookie_monitor import (
    ALERTA_ANTECEDENCIA_DIAS,
    SETTING_ATUALIZADO_EM,
    dias_restantes_estimados,
    verificar_cookie_prestes_a_vencer,
)


class Command(BaseCommand):
    help = (
        'Verifica a estimativa preditiva de expiração do cookie/token de sessão do '
        'Mercado Livre (ML_COOKIE/ML_CSRF_TOKEN) e alerta o operador antes de vencer. '
        'Complementa (não substitui) o alerta reativo já disparado pelo scraper quando '
        'uma chamada autenticada real é rejeitada com HTTP 401/403. Depende da Setting '
        f'"{SETTING_ATUALIZADO_EM}" estar configurada manualmente pelo operador — sem '
        'ela, este comando não alerta (limitação conhecida, ver apps/scraping/services/'
        'ml_cookie_monitor.py).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias-antecedencia',
            type=int,
            default=ALERTA_ANTECEDENCIA_DIAS,
            help=f'Dispara alerta quando faltar N dias ou menos (default: {ALERTA_ANTECEDENCIA_DIAS}).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help=(
                'Roda só a estimativa, sem disparar nenhum alerta real '
                '(útil para testar o comando sem enviar mensagem ao operador).'
            ),
        )

    def handle(self, *args, **options):
        dias_antecedencia = options['dias_antecedencia']
        dry_run = options['dry_run']

        dias_restantes = dias_restantes_estimados()
        if dias_restantes is None:
            self.stdout.write(
                self.style.WARNING(
                    f'Setting "{SETTING_ATUALIZADO_EM}" não configurada — alerta preditivo '
                    'desligado. Defina-a manualmente (timestamp ISO 8601) toda vez que '
                    'renovar o cookie no .env para habilitar esta checagem.',
                ),
            )
            return

        self.stdout.write(f'Estimativa: {dias_restantes} dia(s) restante(s) até a expiração esperada.')

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: nenhum alerta será enviado de verdade.'))
            if dias_restantes <= dias_antecedencia:
                self.stdout.write(self.style.ERROR('Alertaria: cookie prestes a vencer (ou já vencido).'))
            else:
                self.stdout.write(self.style.SUCCESS('OK: dentro da margem de segurança.'))
            return

        if verificar_cookie_prestes_a_vencer(dias_antecedencia):
            self.stdout.write(self.style.ERROR('Cookie prestes a vencer (ou já vencido) — alerta disparado.'))
        else:
            self.stdout.write(self.style.SUCCESS('OK: dentro da margem de segurança.'))
