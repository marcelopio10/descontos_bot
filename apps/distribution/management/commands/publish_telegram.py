import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.services.curated_batch_reader import get_ready_curated_batch
from apps.curation.services.selector import (
    get_selection_config,
    select_offers_for_channel,
)
from apps.curation.services.telegram_message_builder import build_curated_telegram_payload, build_telegram_payload
from apps.distribution.models import SocialChannel
from apps.distribution.services.telegram_delivery import deliver_curated_item_to_telegram, deliver_offer_to_telegram
from apps.orchestration.services.scheduler import (
    sleep_between_cycles,
    wait_until_distribution_window,
)


HOMOLOG_CODE = 'telegram_homolog'
MAIN_CODE = 'telegram_main'

logger = logging.getLogger('apps.distribution.telegram')


class Command(BaseCommand):
    help = 'Publica ofertas elegíveis no canal Telegram (homologação por padrão).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            default=HOMOLOG_CODE,
            choices=[HOMOLOG_CODE, MAIN_CODE],
            help='Código do SocialChannel Telegram alvo.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de ofertas a publicar nesta execução (após o selector).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista as ofertas selecionadas e imprime a caption sem enviar nada.',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Executa 1 ciclo e sai. Sem este flag, entra em loop contínuo (estilo run_bot).',
        )
        parser.add_argument(
            '--ai-curation',
            action='store_true',
            help='Usa lote curado por IA em vez do selector determinístico.',
        )

    def handle(self, *args, **options):
        channel_code = options['channel']
        dry_run = options['dry_run']
        limit = options['limit']

        if channel_code == MAIN_CODE and not settings.ALLOW_PRODUCTION_TELEGRAM_SEND:
            raise CommandError(
                'telegram_main bloqueado: defina ALLOW_PRODUCTION_TELEGRAM_SEND=true.',
            )

        try:
            channel = SocialChannel.objects.get(code=channel_code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(
                f'SocialChannel "{channel_code}" não encontrado. '
                f'Rode `python3 manage.py seed_telegram_channel`.',
            ) from exc

        if not channel.is_enabled:
            raise CommandError(f'Canal {channel_code} desabilitado.')

        if options['once']:
            self._run_cycle(channel=channel, dry_run=dry_run, limit=limit, ai_curation=options['ai_curation'])
            return

        self.stdout.write('Scheduler Telegram iniciado. Use Ctrl+C para parar.')
        logger.info('Scheduler Telegram iniciado. dry_run=%s canal=%s', dry_run, channel.code)
        try:
            while True:
                if not dry_run:
                    wait_until_distribution_window()
                self._run_cycle(channel=channel, dry_run=dry_run, limit=limit, ai_curation=options['ai_curation'])
                seconds = sleep_between_cycles()
                self.stdout.write(f'Próximo ciclo em {seconds // 60} minutos.')
        except KeyboardInterrupt:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Scheduler Telegram interrompido pelo operador.'))
            logger.info('Scheduler Telegram interrompido pelo operador.')

    def _run_cycle(self, channel: SocialChannel, dry_run: bool, limit: int | None, ai_curation: bool = False) -> None:
        if ai_curation:
            self._run_ai_curation_cycle(channel=channel, dry_run=dry_run, limit=limit)
            return

        offers = select_offers_for_channel(channel, get_selection_config())
        if limit is not None:
            offers = offers[: max(0, limit)]

        self.stdout.write(f'Selecionadas {len(offers)} oferta(s) para {channel.code}.')

        if not offers:
            return

        if dry_run:
            for offer in offers:
                payload = build_telegram_payload(offer, channel)
                self.stdout.write('-' * 60)
                self.stdout.write(f'offer_id={offer.id} title={offer.title!r}')
                self.stdout.write(f'use_photo={payload.use_photo} photo_url={payload.photo_url}')
                self.stdout.write(f'button_url={payload.final_url}')
                self.stdout.write('caption:')
                self.stdout.write(payload.caption)
            self.stdout.write(self.style.WARNING('dry_run ativo: nenhuma mensagem real enviada.'))
            return

        sent_count = 0
        for offer in offers:
            result = deliver_offer_to_telegram(offer, channel)
            if result.sent:
                sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Ciclo concluído. Enviadas {sent_count}/{len(offers)} '
                f'no canal {channel.code}.',
            ),
        )

    def _run_ai_curation_cycle(self, channel: SocialChannel, dry_run: bool, limit: int | None) -> None:
        result = get_ready_curated_batch(channel)
        if not result.has_batch:
            self.stdout.write(self.style.WARNING(result.reason or 'Nenhum lote curado pronto para este canal.'))
            logger.info('telegram.ai_curation.paused channel=%s reason=%s', channel.code, result.reason)
            return

        batch = result.batch
        items = result.items
        if limit is not None:
            items = items[: max(0, limit)]
        self.stdout.write(f'Lote curado #{batch.id}: run={batch.run_id}; itens={len(items)}; channel={channel.code}')

        if not items:
            self.stdout.write(self.style.WARNING('Lote curado sem itens pendentes após aplicação do limite.'))
            return

        if dry_run:
            for item in items:
                payload = build_curated_telegram_payload(item, channel)
                self.stdout.write('-' * 60)
                self.stdout.write(f'item_id={item.id} offer_id={item.offer_id} title={item.final_title!r}')
                self.stdout.write(f'use_photo={payload.use_photo} photo_url={payload.photo_url}')
                self.stdout.write(f'button_url={payload.final_url}')
                self.stdout.write('caption:')
                self.stdout.write(payload.caption)
            self.stdout.write(self.style.WARNING('dry_run ativo: nenhuma mensagem real enviada.'))
            return

        sent_count = 0
        for item in items:
            result = deliver_curated_item_to_telegram(item=item, channel=channel)
            if result.sent:
                sent_count += 1
            self.stdout.write(
                f'item_id={item.id} entrega={result.delivery.delivery_status} '
                f'externo={result.delivery.external_message_id or "-"}',
            )
        self.stdout.write(self.style.SUCCESS(f'Enviadas {sent_count}/{len(items)} com curadoria IA.'))
