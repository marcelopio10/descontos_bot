import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.services.message_builder import build_offer_message, get_final_url
from apps.curation.services.selector import get_selection_config, select_offers_for_channel
from apps.distribution.models import SocialChannel
from apps.distribution.services.delivery import deliver_offer_to_channel
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)
from apps.marketplaces.models import Marketplace
from apps.orchestration.services.offer_publication import (
    get_auto_publish_skip_reason,
    publish_offers_after_capture,
)
from apps.orchestration.services.scheduler import (
    calculate_next_sleep_seconds,
    get_scheduler_config,
    sleep_between_cycles,
    wait_until_distribution_window,
)
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping


log = logging.getLogger(__name__)
DEFAULT_CHANNEL_CODE = 'whatsapp_main'
PRODUCTION_WHATSAPP_TARGET = 'descontos.bot'


class Command(BaseCommand):
    help = 'Executa um ciclo local do descontos.bot.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Gera prévia sem enviar mensagens reais e sem gravar entregas.',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Executa apenas um ciclo.',
        )
        parser.add_argument(
            '--channel',
            default=DEFAULT_CHANNEL_CODE,
            help='Código do canal social usado na seleção. Padrão: homologação WhatsApp.',
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=5,
            help='Quantidade máxima de páginas por marketplace em cada ciclo.',
        )
        parser.add_argument(
            '--skip-scraping',
            action='store_true',
            help='Usa somente ofertas já salvas no banco local.',
        )
        parser.add_argument(
            '--show-next-interval',
            action='store_true',
            help='Mostra o intervalo randômico calculado sem dormir.',
        )

    def handle(self, *args, **options):
        max_pages = options['max_pages']
        if max_pages < 1 or max_pages > 5:
            raise CommandError('--max-pages deve ficar entre 1 e 5.')

        dry_run = options['dry_run']
        channel = self._get_channel(options['channel'])
        if not dry_run:
            self._validate_channel_for_real_delivery(channel)

        if options['once']:
            self._run_cycle(
                channel=channel,
                dry_run=dry_run,
                max_pages=max_pages,
                skip_scraping=options['skip_scraping'],
            )
            if options['show_next_interval']:
                self._write_next_interval()
            return

        self.stdout.write('Scheduler local iniciado. Use Ctrl+C para parar.')
        log.info('Scheduler local iniciado. dry_run=%s canal=%s', dry_run, channel.code)

        try:
            while True:
                if not dry_run:
                    wait_until_distribution_window()

                self._run_cycle(
                    channel=channel,
                    dry_run=dry_run,
                    max_pages=max_pages,
                    skip_scraping=options['skip_scraping'],
                )
                seconds = sleep_between_cycles()
                self.stdout.write(
                    f'Próximo ciclo em {seconds // 60} minutos.',
                )
        except KeyboardInterrupt:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Scheduler local interrompido pelo operador.'))
            log.info('Scheduler local interrompido pelo operador.')

    def _run_cycle(
        self,
        channel: SocialChannel,
        dry_run: bool,
        max_pages: int,
        skip_scraping: bool,
    ) -> None:
        log.info('Ciclo iniciado. dry_run=%s canal=%s', dry_run, channel.code)
        self.stdout.write('Início do ciclo local.')

        if skip_scraping:
            self.stdout.write('Scraping ignorado por opção do operador.')
            scraping_summary = None
        else:
            scraping_summary = self._run_scraping(max_pages=max_pages)
            self._publish_after_capture(
                scraping_summary=scraping_summary,
                dry_run=dry_run,
            )

        config = get_selection_config()
        offers = select_offers_for_channel(channel=channel, config=config)

        mode = 'dry_run' if dry_run else 'envio real'
        self.stdout.write(f'Ciclo do descontos.bot em {mode}')
        self.stdout.write(f'Canal: {channel.name} ({channel.code})')
        self.stdout.write(
            (
                f'Limite global: {config.global_limit}; '
                f'limite por marketplace: {config.marketplace_limit}; '
                f'desconto mínimo: {config.min_discount_percentage}%'
            ),
        )
        self.stdout.write(f'Ofertas selecionadas: {len(offers)}')

        if not offers:
            self.stdout.write(self.style.WARNING('Nenhuma oferta elegível encontrada.'))
            log.info('Ciclo finalizado sem ofertas elegíveis.')
            return

        if not dry_run and is_distribution_silenced():
            self.stdout.write(self.style.WARNING(get_silence_error_message()))

        for index, offer in enumerate(offers, start=1):
            message = build_offer_message(offer, channel)
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Oferta {index}/{len(offers)}'))
            self.stdout.write(f'Marketplace: {offer.marketplace.name}')
            self.stdout.write(f'Link final: {get_final_url(offer, channel)}')
            self.stdout.write('Mensagem:')
            self.stdout.write(message)

            if not dry_run:
                result = deliver_offer_to_channel(offer=offer, channel=channel)
                delivery = result.delivery
                self.stdout.write(
                    f'Entrega: {delivery.delivery_status} '
                    f'(id={delivery.id}, externo={delivery.external_message_id or "-"})',
                )
                if delivery.error_message:
                    self.stdout.write(self.style.WARNING(delivery.error_message))

        self.stdout.write('')
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'dry_run ativo: nenhuma mensagem real foi enviada e nenhuma entrega foi gravada.',
                ),
            )
        log.info('Ciclo finalizado. ofertas_selecionadas=%s', len(offers))

    def _run_scraping(self, max_pages: int) -> dict[str, int]:
        self.stdout.write('Início da captura de ofertas nos marketplaces.')
        log.info('Captura iniciada. max_pages=%s', max_pages)
        summary = {
            'marketplaces': 0,
            'failed': 0,
            'partial_failed': 0,
            'total_collected': 0,
            'total_valid': 0,
            'total_created': 0,
            'total_updated': 0,
        }
        marketplaces = Marketplace.objects.filter(is_active=True).order_by('name')
        if not marketplaces.exists():
            self.stdout.write(self.style.WARNING('Nenhum marketplace ativo para coleta.'))
            log.warning('Captura ignorada: nenhum marketplace ativo.')
            return summary

        for marketplace in marketplaces:
            summary['marketplaces'] += 1
            self.stdout.write(f'Coletando ofertas de {marketplace.name}...')
            result = run_marketplace_scraping(
                marketplace=marketplace,
                max_pages=max_pages,
            )
            run = result.run
            summary['total_collected'] += result.total_collected
            summary['total_valid'] += result.total_valid
            summary['total_created'] += result.total_created
            summary['total_updated'] += result.total_updated
            level = self.style.SUCCESS
            if run.status in (
                ScrapingRun.RunStatus.FAILED,
                ScrapingRun.RunStatus.PARTIAL_FAILED,
            ):
                level = self.style.WARNING
            if run.status == ScrapingRun.RunStatus.FAILED:
                summary['failed'] += 1
            if run.status == ScrapingRun.RunStatus.PARTIAL_FAILED:
                summary['partial_failed'] += 1

            self.stdout.write(
                level(
                    (
                        f'{marketplace.name}: {run.status}; '
                        f'coletadas={result.total_collected}; '
                        f'válidas={result.total_valid}; '
                        f'criadas={result.total_created}; '
                        f'atualizadas={result.total_updated}'
                    ),
                ),
            )
            if run.error_message:
                self.stdout.write(self.style.WARNING(f'Aviso: {run.error_message}'))

        self.stdout.write(
            (
                'Captura finalizada: '
                f'processadas={summary["total_valid"]}; '
                f'novas={summary["total_created"]}; '
                f'atualizadas={summary["total_updated"]}; '
                f'coletadas={summary["total_collected"]}'
            ),
        )
        log.info(
            (
                'Captura finalizada. marketplaces=%s coletadas=%s validas=%s '
                'criadas=%s atualizadas=%s falhas=%s falhas_parciais=%s'
            ),
            summary['marketplaces'],
            summary['total_collected'],
            summary['total_valid'],
            summary['total_created'],
            summary['total_updated'],
            summary['failed'],
            summary['partial_failed'],
        )
        return summary

    def _publish_after_capture(self, scraping_summary: dict[str, int], dry_run: bool) -> None:
        skip_reason = get_auto_publish_skip_reason(
            total_valid=scraping_summary['total_valid'],
            dry_run=dry_run,
        )
        if skip_reason:
            self.stdout.write(self.style.WARNING(skip_reason))
            log.info(skip_reason)
            return

        self.stdout.write('Início da publicação automática do offers.json.')
        result = publish_offers_after_capture()
        if result['error']:
            self.stdout.write(self.style.WARNING(f'Erro na publicação automática: {result["error"]}'))
            log.error('Erro na publicação automática: %s', result)
            return

        self.stdout.write(
            (
                'Publicação automática finalizada: '
                f'ofertas={result["offers_count"]}; '
                f'diff={result["changed"]}; '
                f'commit={result["committed"]}; '
                f'push={result["pushed"]}'
            ),
        )
        log.info('Publicação automática finalizada. resultado=%s', result)

    def _write_next_interval(self) -> None:
        config = get_scheduler_config()
        seconds = calculate_next_sleep_seconds(config)
        self.stdout.write(
            (
                f'Intervalo contínuo configurado: '
                f'{config.min_minutes}-{config.max_minutes} minutos. '
                f'Próximo sleep calculado: {seconds // 60} minutos.'
            ),
        )

    def _get_channel(self, code: str) -> SocialChannel:
        try:
            return SocialChannel.objects.get(code=code, is_enabled=True)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(f'Canal ativo "{code}" não encontrado.') from exc

    def _validate_channel_for_real_delivery(self, channel: SocialChannel) -> None:
        if settings.ALLOW_PRODUCTION_WHATSAPP_SEND:
            return

        if channel.target.strip().lower() != PRODUCTION_WHATSAPP_TARGET:
            return

        raise CommandError(
            (
                'Envio real para o grupo de produção "descontos.bot" está bloqueado. '
                f'Use o canal "{DEFAULT_CHANNEL_CODE}" para homologação ou defina '
                'ALLOW_PRODUCTION_WHATSAPP_SEND=true quando produção for liberada.'
            ),
        )
