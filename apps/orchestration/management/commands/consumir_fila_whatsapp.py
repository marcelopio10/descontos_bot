import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.models import CurationRun
from apps.curation.services.curated_batch_reader import get_ready_curated_batch
from apps.curation.services.message_builder import build_curated_offer_message, get_final_url
from apps.distribution.models import SocialChannel
from apps.distribution.services.delivery import (
    SessaoIndisponivelError,
    deliver_curated_item_to_whatsapp,
    get_whatsapp_session_status,
)
from apps.distribution.services.whatsapp_client import WhatsAppClientError


log = logging.getLogger(__name__)

DEFAULT_CHANNEL_CODE = 'whatsapp_main'
PRODUCTION_WHATSAPP_TARGET = 'descontos.bot'
PRODUCTION_WHATSAPP_CHANNEL_CODES = {'whatsapp_principal'}
AI_PRODUCTION_CONFIRMATION = 'CONFIRM_AI_PRODUCTION'


class Command(BaseCommand):
    help = (
        'Consome o lote de curadoria IA já pronto (CuratedBatch status=ready) e envia ao '
        'WhatsApp: é SÓ a metade "consumo/envio" do fluxo desacoplado da Sprint 3 - Tarefa '
        '3.3. O `run_bot` continua responsável por coletar (scraping) e preparar o lote '
        '(prepare_ai_curation_batch); quando a Setting `usa_fila_desacoplada` está ligada, '
        'ele para depois de preparar, e este comando passa a ser quem lê o lote pronto '
        '(get_ready_curated_batch) e chama deliver_curated_item_to_whatsapp por item — a '
        'mesma lógica que hoje roda embutida em run_bot._run_ai_curation_cycle. '
        'Pensado para rodar sozinho, via um timer systemd PRÓPRIO (não instalado por esta '
        'tarefa) — igual ao padrão já usado pelo publish_telegram (scripts/publish-telegram.'
        '{service,timer}). Instalação sugerida (revisar antes de habilitar): criar '
        'scripts/consumir-fila-whatsapp.service com '
        '"ExecStart=.venv/bin/python3 manage.py consumir_fila_whatsapp --channel '
        'whatsapp_principal --confirm-ai-production CONFIRM_AI_PRODUCTION" (Type=oneshot, '
        'nos moldes de publish-telegram.service) e scripts/consumir-fila-whatsapp.timer '
        '(OnUnitActiveSec=Xmin, Unit=consumir-fila-whatsapp.service), depois '
        '`systemctl --user daemon-reload && systemctl --user enable --now '
        'consumir-fila-whatsapp.timer`.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--channel',
            default=DEFAULT_CHANNEL_CODE,
            help='Código do SocialChannel WhatsApp alvo. Padrão: homologação (whatsapp_main).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Máximo de itens do lote curado consumidos nesta execução.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Lista os itens do lote pronto e imprime a mensagem sem enviar nada e sem marcar consumo.',
        )
        parser.add_argument(
            '--confirm-ai-production',
            default='',
            help='Confirma envio assistido em produção. Valor exigido: CONFIRM_AI_PRODUCTION.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        if limit is not None and limit < 1:
            raise CommandError('--limit deve ser maior que zero.')

        channel = self._get_channel(options['channel'])
        if not dry_run:
            self._validate_channel_for_real_delivery(channel)
            self._validate_ai_production_confirmation(channel, options['confirm_ai_production'])

        allowed_modes = (
            [CurationRun.Mode.DRY_RUN] if dry_run else [CurationRun.Mode.HOMOLOG, CurationRun.Mode.PRODUCTION]
        )
        self._consume_ready_batch(channel=channel, dry_run=dry_run, limit=limit, allowed_modes=allowed_modes)

    def _consume_ready_batch(
        self,
        *,
        channel: SocialChannel,
        dry_run: bool,
        limit: int | None,
        allowed_modes: list[str] | None,
    ) -> None:
        result = get_ready_curated_batch(channel, allowed_modes=allowed_modes)
        if not result.has_batch:
            self.stdout.write(self.style.WARNING(result.reason or 'Nenhum lote curado pronto.'))
            log.info('consumir_fila_whatsapp.paused channel=%s reason=%s', channel.code, result.reason)
            return

        batch = result.batch
        items = result.items
        if limit is not None:
            items = items[:limit]
        mode = 'dry_run' if dry_run else 'homologação/envio real'
        self.stdout.write(f'Consumo da fila desacoplada em {mode}')
        self.stdout.write(f'Canal: {channel.name} ({channel.code})')
        self.stdout.write(f'Lote curado #{batch.id}: run={batch.run_id}; itens={len(items)}')

        if not items:
            self.stdout.write(self.style.WARNING('Lote curado sem itens pendentes após aplicação do limite.'))
            return

        if not dry_run and not self._check_whatsapp_session():
            return

        for index, item in enumerate(items, start=1):
            offer = item.offer
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Oferta curada {index}/{len(items)}'))
            self.stdout.write(f'Marketplace: {offer.marketplace.name}')
            self.stdout.write(f'Link final: {get_final_url(offer, channel)}')
            self.stdout.write(f'Título: {item.final_title}')
            self.stdout.write('Mensagem:')
            self.stdout.write(build_curated_offer_message(item, channel))

            if dry_run:
                continue

            try:
                delivery_result = deliver_curated_item_to_whatsapp(item=item, channel=channel)
            except SessaoIndisponivelError as exc:
                self.stdout.write(
                    self.style.ERROR(f'Sessão do WhatsApp caiu durante o envio: {exc}'),
                )
                log.error(
                    'whatsapp_session.dropped_mid_batch offer_id=%s item_id=%s motivo=%s',
                    offer.id, item.id, exc,
                )
                break
            delivery = delivery_result.delivery
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
        else:
            sent_count = sum(1 for item in items if item.send_status == item.SendStatus.SENT)
            self.stdout.write(self.style.SUCCESS(f'Enviadas {sent_count}/{len(items)} com curadoria IA.'))
        log.info(
            'consumir_fila_whatsapp.cycle_finished batch_id=%s items=%s dry_run=%s',
            batch.id, len(items), dry_run,
        )

    def _check_whatsapp_session(self) -> bool:
        """Checa a sessão do WhatsApp uma única vez antes de iniciar o consumo do lote.

        Mesma lógica de guarda usada em run_bot._check_whatsapp_session (achado C3):
        se a sessão já está indisponível, não iteramos os itens nem marcamos nada
        como falho — os itens seguem `pendente` no lote para o próximo ciclo deste
        comando.
        """
        try:
            status = get_whatsapp_session_status()
        except WhatsAppClientError as exc:
            self.stdout.write(self.style.ERROR(f'Sessão do WhatsApp indisponível: {exc}'))
            log.error('whatsapp_session.precheck_failed motivo=%s', exc)
            return False
        if not status.connected:
            self.stdout.write(
                self.style.ERROR(
                    'Sessão do WhatsApp não conectada. Consumo abortado antes do envio; '
                    'os itens continuam pendentes no lote para a próxima execução.',
                ),
            )
            log.error('whatsapp_session.precheck_failed motivo=nao_conectado')
            return False
        return True

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

    def _validate_ai_production_confirmation(self, channel: SocialChannel, confirmation: str) -> None:
        is_production_channel = (
            channel.code in PRODUCTION_WHATSAPP_CHANNEL_CODES
            or channel.target.strip().lower() == PRODUCTION_WHATSAPP_TARGET
        )
        if not is_production_channel:
            return
        if confirmation == AI_PRODUCTION_CONFIRMATION:
            return
        raise CommandError(
            '--confirm-ai-production CONFIRM_AI_PRODUCTION é obrigatório para envio IA em produção.',
        )
