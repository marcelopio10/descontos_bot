import logging
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.curation.models import CurationRun
from apps.curation.services.blacklist import filter_blacklisted_offers
from apps.curation.services.curated_batch_reader import get_ready_curated_batch
from apps.curation.services.message_builder import build_curated_offer_message, build_offer_message, get_final_url
from apps.curation.services.selector import get_selection_config, select_offers_for_channel
from apps.curation.services.settings import get_bool_setting
from apps.distribution.models import SocialChannel
from apps.distribution.services.delivery import (
    SessaoIndisponivelError,
    deliver_curated_item_to_whatsapp,
    deliver_offer_to_channel,
    get_whatsapp_session_status,
)
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)
from apps.distribution.services.whatsapp_client import WhatsAppClientError
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.orchestration.services.offer_publication import (
    get_auto_publish_skip_reason,
    publish_offers_after_capture,
)
from apps.orchestration.services.scheduler import (
    calculate_next_sleep_seconds,
    get_channel_cadence_config,
    get_scheduler_config,
    sleep_between_cycles,
    wait_until_distribution_window,
)
from apps.scraping.models import ScrapingRun
from apps.scraping.services.runner import run_marketplace_scraping
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.post_generator import generate_story_for_offer


log = logging.getLogger(__name__)
DEFAULT_CHANNEL_CODE = 'whatsapp_main'
PRODUCTION_WHATSAPP_TARGET = 'descontos.bot'
PRODUCTION_WHATSAPP_CHANNEL_CODES = {'whatsapp_principal'}
AI_PRODUCTION_CONFIRMATION = 'CONFIRM_AI_PRODUCTION'
INSTAGRAM_GENERATION_WINDOW_HOURS = 36
HEALTHCHECK_FILE = Path(settings.BASE_DIR) / 'data' / 'last_cycle.txt'

# Curadoria IA: mesmo profile em todas as tentativas; muda apenas o modelo/provider.
# O modelo padrão do profile (gpt-5.5) costuma estourar limite de token/latência; o
# fallback força um modelo mais leve/estável de outro provider (glm-5.2), sem trocar
# de profile. Sobrescrevível por env para operação sem deploy.
AI_CURATION_PROFILE = 'descontos-bot'
AI_CURATION_FALLBACK_MODELS = ('glm-5.2',)
AI_CURATION_RUNNER_TIMEOUT = 600

# Sprint 3 - Tarefa 3.3: com esta Setting ligada, `run_bot` só coleta e prepara o
# lote de curadoria IA (enfileira); o consumo/envio passa a rodar em processo
# separado via `manage.py consumir_fila_whatsapp`. Default off: comportamento
# idêntico ao atual (preparar + consumir no mesmo ciclo). Rollback = desligar.
DECOUPLED_QUEUE_SETTING_KEY = 'usa_fila_desacoplada'


def _ai_curation_attempts() -> list[tuple[str, str | None]]:
    """Tentativas de curadoria IA no MESMO profile, na ordem de execução.

    Cada item é (label, model_override): o primário usa o modelo padrão do profile
    (model_override=None) e os fallbacks forçam outro modelo via `hermes -m <modelo>`.
    Env override: AI_CURATION_FALLBACK_MODELS="glm-5.2,glm-4.6" (CSV de modelos de fallback).
    """
    raw = os.environ.get('AI_CURATION_FALLBACK_MODELS', '').strip()
    if raw:
        fallback_models: tuple[str, ...] = tuple(item.strip() for item in raw.split(',') if item.strip())
    else:
        fallback_models = AI_CURATION_FALLBACK_MODELS
    attempts: list[tuple[str, str | None]] = [('primário (modelo padrão do profile)', None)]
    attempts.extend((f'fallback IA ({model})', model) for model in fallback_models)
    return attempts


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
        parser.add_argument(
            '--ai-curation',
            action='store_true',
            help='Usa lote curado por IA em vez do selector determinístico. Mantido por compatibilidade; agora é o padrão.',
        )
        parser.add_argument(
            '--legacy-selector',
            action='store_true',
            help='Opt-out explícito: usa o selector determinístico legado sem curadoria IA.',
        )
        parser.add_argument(
            '--ai-curation-required',
            action='store_true',
            help='Exige lote curado pronto; se ausente, pausa sem fallback.',
        )
        parser.add_argument(
            '--prepare-ai-curation',
            action='store_true',
            help='Prepara lote de curadoria IA antes de consumir.',
        )
        parser.add_argument(
            '--confirm-ai-production',
            default='',
            help='Confirma envio assistido em produção. Valor exigido: CONFIRM_AI_PRODUCTION.',
        )
        parser.add_argument(
            '--ai-curation-limit',
            type=int,
            default=None,
            help='Limita quantidade de itens curados consumidos neste ciclo.',
        )

    def handle(self, *args, **options):
        max_pages = options['max_pages']
        if max_pages < 1 or max_pages > 5:
            raise CommandError('--max-pages deve ficar entre 1 e 5.')

        dry_run = options['dry_run']
        legacy_selector = options['legacy_selector']
        ai_curation = not legacy_selector or options['ai_curation'] or options['ai_curation_required']
        # Só bloqueia o fallback legado quando o operador exige explicitamente lote curado.
        # No fluxo padrão, a IA falhando cai no selector legado como segundo fallback.
        ai_curation_required = options['ai_curation_required']
        prepare_ai_curation = options['prepare_ai_curation'] or (ai_curation and not legacy_selector)
        ai_curation_limit = options['ai_curation_limit']
        if ai_curation_limit is not None and ai_curation_limit < 1:
            raise CommandError('--ai-curation-limit deve ser maior que zero.')
        channel = self._get_channel(options['channel'])
        if not dry_run:
            self._validate_channel_for_real_delivery(channel)
            if ai_curation:
                self._validate_ai_production_confirmation(channel, options['confirm_ai_production'])

        if options['once']:
            self._run_cycle(
                channel=channel,
                dry_run=dry_run,
                max_pages=max_pages,
                skip_scraping=options['skip_scraping'],
                ai_curation=ai_curation,
                ai_curation_required=ai_curation_required,
                prepare_ai_curation=prepare_ai_curation,
                ai_curation_limit=ai_curation_limit,
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
                    ai_curation=ai_curation,
                    ai_curation_required=ai_curation_required,
                    prepare_ai_curation=prepare_ai_curation,
                    ai_curation_limit=ai_curation_limit,
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
        ai_curation: bool,
        ai_curation_required: bool,
        prepare_ai_curation: bool,
        ai_curation_limit: int | None = None,
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
            self._generate_instagram_posts_for_new_offers()

        if prepare_ai_curation:
            self._prepare_ai_curation(channel=channel, dry_run=dry_run)

        if ai_curation:
            if self._usa_fila_desacoplada():
                self.stdout.write(
                    self.style.WARNING(
                        'Fila desacoplada ativa (Setting usa_fila_desacoplada=on): ciclo só '
                        'coleta e prepara o lote. Consumo/envio roda em processo separado '
                        '(`manage.py consumir_fila_whatsapp`).',
                    ),
                )
                log.info('ai_curation.decoupled_queue_prepare_only canal=%s', channel.code)
                self._write_healthcheck()
                return
            allowed_modes = [CurationRun.Mode.DRY_RUN] if dry_run else [CurationRun.Mode.HOMOLOG, CurationRun.Mode.PRODUCTION]
            if ai_curation_required:
                self.stdout.write(self.style.WARNING('ai-curation-required ativo: fallback para selector legado bloqueado.'))
            if self._run_ai_curation_cycle(channel=channel, dry_run=dry_run, limit=ai_curation_limit, allowed_modes=allowed_modes):
                return
            if ai_curation_required:
                self.stdout.write(self.style.ERROR('ai-curation-required: abortando ciclo sem fallback para selector legado.'))
                self._write_healthcheck()
                return
            self.stdout.write(
                self.style.WARNING(
                    'Curadoria IA indisponível (tentativas de IA falharam). '
                    'Usando selector legado por lógica como segundo fallback.',
                ),
            )
            log.warning('ai_curation.fallback_to_legacy canal=%s', channel.code)

        config = get_selection_config()
        offers = select_offers_for_channel(channel=channel, config=config)
        offers = self._apply_channel_cadence(channel=channel, items=offers)

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
            self._write_healthcheck()
            return

        if not dry_run and is_distribution_silenced():
            self.stdout.write(self.style.WARNING(get_silence_error_message()))

        if not dry_run and not self._check_whatsapp_session():
            self._write_healthcheck()
            return

        for index, offer in enumerate(offers, start=1):
            message = build_offer_message(offer, channel)
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Oferta {index}/{len(offers)}'))
            self.stdout.write(f'Marketplace: {offer.marketplace.name}')
            self.stdout.write(f'Link final: {get_final_url(offer, channel)}')
            self.stdout.write('Mensagem:')
            self.stdout.write(message)

            if not dry_run:
                try:
                    result = deliver_offer_to_channel(offer=offer, channel=channel)
                except SessaoIndisponivelError as exc:
                    self.stdout.write(
                        self.style.ERROR(f'Sessão do WhatsApp caiu durante o envio: {exc}'),
                    )
                    log.error(
                        'whatsapp_session.dropped_mid_batch offer_id=%s motivo=%s',
                        offer.id, exc,
                    )
                    break
                delivery = result.delivery
                self.stdout.write(
                    f'Entrega: {delivery.delivery_status} '
                    f'(id={delivery.id}, externo={delivery.external_message_id or "-"})',
                )
                if delivery.error_message:
                    self.stdout.write(self.style.WARNING(delivery.error_message))
                if result.sent:
                    self._generate_instagram_story(offer)

        self.stdout.write('')
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    'dry_run ativo: nenhuma mensagem real foi enviada e nenhuma entrega foi gravada.',
                ),
            )
        log.info('Ciclo finalizado. ofertas_selecionadas=%s', len(offers))
        self._write_healthcheck()

    def _prepare_ai_curation(self, *, channel: SocialChannel, dry_run: bool) -> bool:
        """Prepara o lote de curadoria IA tentando o profile primário e, se falhar,
        o mesmo profile com um modelo de fallback (outro provider).

        Retorna True na primeira tentativa que preparar o lote sem erro; False se
        todas falharem (o chamador então cai no selector legado).
        """
        for label, model_override in _ai_curation_attempts():
            prepare_args = [
                'prepare_ai_curation_batch',
                '--channel',
                channel.code,
                '--mode',
                'dry_run' if dry_run else 'homolog',
                '--runner',
                'real',
                '--profile',
                AI_CURATION_PROFILE,
                '--skip-images',
                '--runner-timeout',
                str(AI_CURATION_RUNNER_TIMEOUT),
            ]
            if model_override:
                prepare_args += ['--model', model_override]
            if dry_run:
                prepare_args.append('--dry-run')

            self.stdout.write(f'Preparando lote de curadoria IA ({label}, profile={AI_CURATION_PROFILE}).')
            try:
                call_command(*prepare_args, stdout=self.stdout)
            except CommandError as exc:
                log.error(
                    'ai_curation.prepare_failed canal=%s profile=%s modelo=%s erro=%s',
                    channel.code, AI_CURATION_PROFILE, model_override or 'default', exc,
                )
                self.stdout.write(self.style.ERROR(f'Preparação IA falhou ({label}): {exc}'))
                continue
            log.info(
                'ai_curation.prepare_ok canal=%s profile=%s modelo=%s',
                channel.code, AI_CURATION_PROFILE, model_override or 'default',
            )
            return True
        return False

    def _usa_fila_desacoplada(self) -> bool:
        """Setting `usa_fila_desacoplada` (Sprint 3 - Tarefa 3.3). Default False:
        mantém o comportamento atual (preparar + consumir no mesmo ciclo).
        """
        return get_bool_setting(DECOUPLED_QUEUE_SETTING_KEY, False)

    def _run_ai_curation_cycle(self, *, channel: SocialChannel, dry_run: bool, limit: int | None = None, allowed_modes: list[str] | None = None) -> bool:
        result = get_ready_curated_batch(channel, allowed_modes=allowed_modes)
        if not result.has_batch:
            self.stdout.write(self.style.WARNING(result.reason or 'Nenhum lote curado pronto.'))
            log.info('ai_curation.paused channel=%s reason=%s', channel.code, result.reason)
            return False

        batch = result.batch
        items = result.items
        if limit is not None:
            items = items[:limit]
        else:
            items = self._apply_channel_cadence(channel=channel, items=items)
        mode = 'dry_run' if dry_run else 'homologação/envio real'
        self.stdout.write(f'Ciclo do descontos.bot em {mode} com curadoria IA')
        self.stdout.write(f'Canal: {channel.name} ({channel.code})')
        self.stdout.write(f'Lote curado #{batch.id}: run={batch.run_id}; itens={len(items)}')

        if not dry_run and not self._check_whatsapp_session():
            self._write_healthcheck()
            return True

        for index, item in enumerate(items, start=1):
            offer = item.offer
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'Oferta curada {index}/{len(items)}'))
            self.stdout.write(f'Marketplace: {offer.marketplace.name}')
            self.stdout.write(f'Link final: {get_final_url(offer, channel)}')
            self.stdout.write(f'Título: {item.final_title}')
            self.stdout.write('Mensagem:')
            self.stdout.write(build_curated_offer_message(item, channel))

            if not dry_run:
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
        log.info('ai_curation.cycle_finished batch_id=%s items=%s dry_run=%s', batch.id, len(items), dry_run)
        self._write_healthcheck()
        return True

    def _check_whatsapp_session(self) -> bool:
        """Checa a sessão do WhatsApp uma única vez antes de iniciar o loop de envio.

        Evita o cenário do achado C3: se a sessão já está indisponível antes do
        ciclo começar a enviar, não iteramos as ofertas nem marcamos nada como
        FAILED — apenas registramos o motivo e saímos cedo. As ofertas seguem
        elegíveis para o próximo ciclo.
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
                    'Sessão do WhatsApp não conectada. Ciclo abortado antes do envio; '
                    'as ofertas continuam elegíveis no próximo ciclo.',
                ),
            )
            log.error('whatsapp_session.precheck_failed motivo=nao_conectado')
            return False
        return True

    def _apply_channel_cadence(self, *, channel: SocialChannel, items: list) -> list:
        """Aplica o teto/piso de cadência configurado para o canal (Tarefa 1.4).

        Teto: corta rajadas limitando itens/ciclo. Piso: não força itens
        inexistentes a aparecer — apenas registra quando o lote elegível fica
        abaixo do piso configurado (não há o que enviar além do que existe).
        """
        cadence = get_channel_cadence_config()
        total = len(items)
        capped = items[: cadence.max_items_per_cycle]
        if len(capped) < total:
            self.stdout.write(
                self.style.WARNING(
                    f'Cadência: lote reduzido de {total} para {len(capped)} '
                    f'(teto configurado: {cadence.max_items_per_cycle}/ciclo, canal={channel.code}).',
                ),
            )
            log.info(
                'channel_cadence.capped canal=%s total=%s teto=%s',
                channel.code, total, cadence.max_items_per_cycle,
            )
        elif 0 < total < cadence.min_items_per_cycle:
            self.stdout.write(
                self.style.WARNING(
                    f'Cadência abaixo do piso configurado ({total} < {cadence.min_items_per_cycle}) '
                    f'para o canal={channel.code}: não há itens elegíveis suficientes.',
                ),
            )
            log.info(
                'channel_cadence.below_floor canal=%s total=%s piso=%s',
                channel.code, total, cadence.min_items_per_cycle,
            )
        return capped

    def _write_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(timezone.now().isoformat() + '\n')
        except Exception as exc:
            log.warning('healthcheck.write_failed erro=%s', exc)

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

    def _generate_instagram_posts_for_new_offers(self) -> None:
        self.stdout.write(
            self.style.WARNING(
                'Geração automática de posts no Instagram está desativada. '
                'Nenhum post foi gerado e nenhum handoff pro Telegram foi disparado.',
            ),
        )
        log.info('instagram_posts.generation_disabled scope=new_offers')
        return

        cutoff = timezone.now() - timedelta(hours=INSTAGRAM_GENERATION_WINDOW_HOURS)
        posted_offer_ids = set(
            InstagramPost.objects
            .filter(format=InstagramPost.Format.STORY)
            .values_list('primary_offer_id', flat=True),
        )
        candidate_offers = list(
            Offer.objects
            .select_related('marketplace')
            .filter(is_active=True, last_seen_at__gte=cutoff)
            .exclude(id__in=posted_offer_ids)
            .order_by('-discount_pct', 'current_price', 'title'),
        )
        offers = filter_blacklisted_offers(candidate_offers)
        blocked_by_blacklist = len(candidate_offers) - len(offers)
        if blocked_by_blacklist:
            self.stdout.write(
                self.style.WARNING(
                    f'{blocked_by_blacklist} oferta(s) bloqueada(s) pela blacklist de segurança.',
                ),
            )
        if not offers:
            self.stdout.write(
                f'Nenhuma oferta nova (últimas {INSTAGRAM_GENERATION_WINDOW_HOURS}h) '
                'para gerar post no Instagram.',
            )
            log.info(
                'instagram_posts.generation_skipped reason=no_new_offers window_hours=%s',
                INSTAGRAM_GENERATION_WINDOW_HOURS,
            )
            return

        self.stdout.write(
            f'Geração de posts Instagram (janela {INSTAGRAM_GENERATION_WINDOW_HOURS}h): '
            f'{len(offers)} oferta(s) candidata(s).',
        )
        log.info(
            'instagram_posts.generation_started total_candidates=%s window_hours=%s',
            len(offers), INSTAGRAM_GENERATION_WINDOW_HOURS,
        )

        generated = 0
        skipped = 0
        for offer in offers:
            try:
                post = generate_story_for_offer(offer)
            except Exception as exc:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'Oferta #{offer.id} ({offer.marketplace.code}) pulada: {exc}',
                    ),
                )
                log.warning(
                    'instagram_posts.generation_failed offer_id=%s marketplace=%s erro=%s',
                    offer.id, offer.marketplace.code, exc,
                )
                continue
            generated += 1
            log.info(
                'instagram_posts.generated offer_id=%s post_id=%s',
                offer.id, post.id,
            )

        self.stdout.write(
            f'Posts Instagram: gerados={generated}; pulados={skipped}.',
        )
        log.info(
            'instagram_posts.generation_finished gerados=%s pulados=%s',
            generated, skipped,
        )

    def _generate_instagram_story(self, offer) -> None:
        self.stdout.write(
            self.style.WARNING(
                'Geração automática de story no Instagram está desativada. '
                'Nenhuma story foi gerada e nenhum handoff pro Telegram foi disparado.',
            ),
        )
        log.info('instagram_story.generation_disabled offer_id=%s', offer.id)
        return

        try:
            post = generate_story_for_offer(offer)
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f'Story Instagram não gerado: {exc}'),
            )
            log.warning(
                'instagram_story.generation_failed offer_id=%s erro=%s',
                offer.id, exc,
            )
            return

        image_path = post.asset_paths[0] if post.asset_paths else ''
        self.stdout.write(self.style.SUCCESS(f'Story Instagram pronto (id={post.id}).'))
        if image_path:
            self.stdout.write(f'Imagem: {image_path}')
        if post.sticker_target_url:
            self.stdout.write(f'Link do sticker: {post.sticker_target_url}')

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
