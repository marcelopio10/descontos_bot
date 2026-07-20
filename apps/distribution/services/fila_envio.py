"""Fila de reenvio de `Delivery` com retry, backoff exponencial e dead-letter.

Contexto (Sprint 3 - Tarefa 3.1 do plano de refatoração pós-diagnóstico):
quando a sessão do WhatsApp cai no meio de um lote, os itens ainda não
enviados ficam com `CuratedBatchItem.send_status='pending'` (sem `Delivery`
criado) e são automaticamente reprocessados no próximo ciclo do `run_bot` —
isso já cobre boa parte do "retry" para o caso de sessão fora do ar. O que
faltava, e que este módulo resolve, é: (1) uma política de quantas vezes
tentar antes de desistir de vez (dead-letter) para o caso de uma `Delivery`
específica que já FALHOU e continua falhando por outro motivo (payload
inválido, oferta com dado ruim etc.), e (2) backoff entre tentativas em vez
de tentar de novo imediatamente a cada ciclo.

Decisão de design 1 — WhatsApp vs Telegram
-------------------------------------------
`SocialChannel.channel_type` já distingue os transportes de forma confiável
(`WHATSAPP`, `WHATSAPP_GROUP`, `WHATSAPP_CHANNEL` vs `TELEGRAM_CHANNEL`).
Usamos essa distinção para escolher entre o caminho de entrega WhatsApp
(`apps.distribution.services.delivery`) e o caminho Telegram
(`apps.distribution.services.telegram_delivery`).

Decisão de design 2 — reenviar via `Offer` direto, não via `CuratedBatchItem`
------------------------------------------------------------------------------
`CuratedBatchItem.delivery` é uma FK (não OneToOne) de item → entrega, então
dado um `Delivery` já não há garantia de que exista exatamente um
`CuratedBatchItem` "vivo" e correspondente para reconstituir o caminho de
entrega curado (`deliver_curated_item_to_whatsapp`/`deliver_curated_item_to_telegram`):
o lote pode já ter mudado de status (`SENT`/`FAILED`/`EXPIRED`), a decisão de
curadoria pode ter sido substituída por um lote mais novo, e nada garante que
a caption/imagem curada originalmente escolhida ainda seja a mais adequada
tempos depois. Reprocessar por cima de um `CuratedBatchItem` potencialmente
obsoleto arrisca reescrever estado de um lote que outro consumidor já está
tratando.

Por isso a fila reenvia sempre pelo caminho legado orientado a `Offer`
(`deliver_offer_to_channel`/`deliver_offer_to_telegram`, sem curadoria IA):
esses caminhos já são idempotentes em cima do MESMO registro `Delivery`
(consultam/reservam por `(offer, social_channel)`), então continuam
atualizando a mesma linha que está sendo processada aqui — só a mensagem
deixa de ser a caption "curada" e passa a ser a mensagem determinística do
`message_builder`/`telegram_message_builder` legado. Isso é uma limitação
conhecida e aceita: um item que falhou após ter sido selecionado pela
curadoria IA, ao ser reenviado pela fila, sai com o texto legado. Se no
futuro for necessário preservar a caption curada no retry, é preciso either
(a) guardar a mensagem final na própria `Delivery` (ela já tem `message`) e
reenviar usando exatamente esse texto salvo, ou (b) resolver de forma
confiável qual `CuratedBatchItem` (se algum) ainda é o "dono" da entrega.

Decisão de design 3 — sessão do WhatsApp indisponível não é falha do item
---------------------------------------------------------------------------
Espelhando a mitigação da Tarefa 1.3 (`SessaoIndisponivelError`), esta fila
faz um pré-check ÚNICO da sessão do WhatsApp antes de percorrer os itens
elegíveis desse transporte. Se a sessão estiver indisponível, os itens
WhatsApp elegíveis são pulados NESTE ciclo sem consumir tentativa/backoff —
do contrário, uma queda de sessão (problema de infraestrutura, não do item)
queimaria o orçamento de `MAX_RETRIES` de todos os itens pendentes em poucos
ciclos e mandaria tudo para dead-letter por um motivo que nada tem a ver com
a oferta em si. Itens do Telegram continuam sendo processados normalmente
mesmo com o WhatsApp indisponível (transportes independentes).
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.analytics.services.alertas import enviar_alerta_operador
from apps.curation.services.settings import get_integer_setting
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.delivery import (
    SessaoIndisponivelError,
    deliver_offer_to_channel,
    get_whatsapp_session_status,
)
from apps.distribution.services.telegram_delivery import deliver_offer_to_telegram
from apps.distribution.services.telegram_client import TelegramClientError
from apps.distribution.services.whatsapp_client import WhatsAppClientError

log = logging.getLogger('apps.distribution.fila_envio')

# Número máximo de tentativas de reenvio pela fila antes do dead-letter.
# Configurável via `panel.Setting` (chave 'fila_envio_max_retries'); default 5.
MAX_RETRIES = 5

# Backoff exponencial em minutos: 2**retry_count, com teto.
BACKOFF_BASE_MINUTES = 2
BACKOFF_CAP_MINUTES = 60

WHATSAPP_CHANNEL_TYPES = {
    SocialChannel.ChannelType.WHATSAPP,
    SocialChannel.ChannelType.WHATSAPP_GROUP,
    SocialChannel.ChannelType.WHATSAPP_CHANNEL,
}
TELEGRAM_CHANNEL_TYPES = {
    SocialChannel.ChannelType.TELEGRAM_CHANNEL,
}


def get_max_retries() -> int:
    return get_integer_setting('fila_envio_max_retries', MAX_RETRIES)


@dataclass(frozen=True)
class RetryOutcome:
    """Resultado do processamento de UM `Delivery` elegível pela fila.

    `status` sempre reflete o que de fato aconteceu no banco (retry agendado,
    dead-letter, enviado, etc.). `session_down` é uma informação ortogonal:
    sinaliza ao loop de `process_queue` que a sessão do WhatsApp caiu durante
    esta tentativa (race com o pré-check), para poupar os itens WhatsApp
    restantes neste ciclo — mesmo que este item específico já tenha
    consumido uma tentativa normalmente (`status` continua sendo
    `retry_scheduled`/`dead_letter`, não é reclassificado como "pulado").
    """

    delivery_id: int
    offer_id: int
    channel_code: str
    status: str  # ver constantes OUTCOME_* abaixo
    detail: str = ''
    session_down: bool = False


OUTCOME_SENT = 'sent'
OUTCOME_RETRY_SCHEDULED = 'retry_scheduled'
OUTCOME_DEAD_LETTER = 'dead_letter'
OUTCOME_SKIPPED_SESSION_DOWN = 'skipped_session_down'
OUTCOME_SKIPPED_EXTERNAL = 'skipped_external'
OUTCOME_SKIPPED_UNSUPPORTED_CHANNEL = 'skipped_unsupported_channel'
OUTCOME_WOULD_RETRY = 'would_retry'  # apenas em dry-run


@dataclass
class QueueProcessingSummary:
    outcomes: list[RetryOutcome] = field(default_factory=list)

    def add(self, outcome: RetryOutcome) -> None:
        self.outcomes.append(outcome)

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    @property
    def sent(self) -> int:
        return self.count(OUTCOME_SENT)

    @property
    def dead_lettered(self) -> int:
        return self.count(OUTCOME_DEAD_LETTER)

    @property
    def retry_scheduled(self) -> int:
        return self.count(OUTCOME_RETRY_SCHEDULED)

    @property
    def skipped(self) -> int:
        return (
            self.count(OUTCOME_SKIPPED_SESSION_DOWN)
            + self.count(OUTCOME_SKIPPED_EXTERNAL)
            + self.count(OUTCOME_SKIPPED_UNSUPPORTED_CHANNEL)
        )

    @property
    def would_retry(self) -> int:
        return self.count(OUTCOME_WOULD_RETRY)


def get_eligible_deliveries(limit: int | None = None) -> list[Delivery]:
    """`Delivery` FAILED, com tentativas restantes e fora (ou sem) backoff."""
    now = timezone.now()
    max_retries = get_max_retries()
    qs = (
        Delivery.objects.filter(
            delivery_status=Delivery.DeliveryStatus.FAILED,
            retry_count__lt=max_retries,
        )
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        .select_related('offer', 'social_channel')
        .order_by('next_retry_at', 'created_at')
    )
    if limit is not None:
        qs = qs[: max(0, limit)]
    return list(qs)


def process_queue(limit: int | None = None, dry_run: bool = False) -> QueueProcessingSummary:
    """Consome a fila de `Delivery` elegíveis para retry.

    Não reenvia nada que já esteja `SENT` (a query já filtra `FAILED`, e os
    caminhos de entrega reusados fazem sua própria checagem/reserva
    idempotente por `(offer, social_channel)` antes de qualquer envio real).
    """
    eligible = get_eligible_deliveries(limit=limit)
    summary = QueueProcessingSummary()

    if dry_run:
        for delivery in eligible:
            summary.add(
                RetryOutcome(
                    delivery_id=delivery.id,
                    offer_id=delivery.offer_id,
                    channel_code=delivery.social_channel.code,
                    status=OUTCOME_WOULD_RETRY,
                    detail=(
                        f'tentativa {delivery.retry_count + 1}/{get_max_retries()} '
                        f'via {delivery.social_channel.channel_type}'
                    ),
                ),
            )
        return summary

    whatsapp_session_down = _precheck_whatsapp_session(eligible)

    for delivery in eligible:
        channel_type = delivery.social_channel.channel_type

        if channel_type in WHATSAPP_CHANNEL_TYPES and whatsapp_session_down:
            summary.add(
                RetryOutcome(
                    delivery_id=delivery.id,
                    offer_id=delivery.offer_id,
                    channel_code=delivery.social_channel.code,
                    status=OUTCOME_SKIPPED_SESSION_DOWN,
                    detail='Sessão do WhatsApp indisponível; tentativa não consumida.',
                ),
            )
            continue

        outcome = _process_one(delivery)
        summary.add(outcome)

        if outcome.session_down:
            # Race entre o pré-check e este item: sessão caiu durante o loop.
            # Poupa o restante dos itens WhatsApp deste ciclo (o item atual já
            # teve sua tentativa/backoff contabilizada normalmente acima).
            whatsapp_session_down = True

    return summary


def _precheck_whatsapp_session(eligible: list[Delivery]) -> bool:
    """Pré-checa a sessão do WhatsApp UMA vez, se houver item WhatsApp elegível.

    Reusa `get_whatsapp_session_status` (o mesmo client/fábrica do caminho de
    envio normal) para não duplicar lógica nem sessão. Retorna True se a
    sessão estiver indisponível (não deve tentar nenhum item WhatsApp neste
    ciclo).
    """
    has_whatsapp_item = any(
        delivery.social_channel.channel_type in WHATSAPP_CHANNEL_TYPES for delivery in eligible
    )
    if not has_whatsapp_item:
        return False

    try:
        status = get_whatsapp_session_status()
    except WhatsAppClientError as exc:
        log.warning('fila_envio.whatsapp_session_check_failed error=%s', exc)
        return True

    return not status.connected


def _process_one(delivery: Delivery) -> RetryOutcome:
    channel = delivery.social_channel
    offer = delivery.offer
    channel_type = channel.channel_type

    try:
        if channel_type in WHATSAPP_CHANNEL_TYPES:
            deliver_offer_to_channel(offer, channel)
        elif channel_type in TELEGRAM_CHANNEL_TYPES:
            deliver_offer_to_telegram(offer, channel)
        else:
            log.error(
                'fila_envio.canal_nao_suportado delivery_id=%s channel_type=%s',
                delivery.id, channel_type,
            )
            return RetryOutcome(
                delivery_id=delivery.id,
                offer_id=offer.id,
                channel_code=channel.code,
                status=OUTCOME_SKIPPED_UNSUPPORTED_CHANNEL,
                detail=f'channel_type={channel_type} sem caminho de entrega conhecido.',
            )
    except SessaoIndisponivelError as exc:
        # A `Delivery` já foi salva como FAILED com o motivo pelo próprio
        # `deliver_offer_to_channel` antes de levantar esta exceção. Ainda
        # assim contabiliza a tentativa/backoff normalmente: se o pré-check
        # não pegou a queda (race), este item reflete uma falha real que de
        # fato foi tentada. `session_down=True` só avisa o loop chamador
        # para poupar o restante dos itens WhatsApp deste ciclo.
        log.warning(
            'fila_envio.sessao_indisponivel delivery_id=%s offer_id=%s error=%s',
            delivery.id, offer.id, exc,
        )
        outcome = _handle_failed_attempt(delivery.id)
        return replace(outcome, session_down=True)
    except TelegramClientError as exc:
        log.warning(
            'fila_envio.telegram_client_error delivery_id=%s offer_id=%s error=%s',
            delivery.id, offer.id, exc,
        )
        return _handle_failed_attempt(delivery.id)

    return _handle_completed_attempt(delivery.id)


def _handle_completed_attempt(delivery_id: int) -> RetryOutcome:
    """Lê o estado pós-tentativa direto do banco e decide o desfecho.

    Os caminhos de entrega reusados (`deliver_offer_to_channel`/
    `deliver_offer_to_telegram`) só tocam os campos deles (`delivery_status`,
    `message`, `external_message_id`, `error_message`, `sent_at`) via
    `update_fields` explícito — `retry_count`/`next_retry_at` nunca são
    sobrescritos por eles, então é seguro reler e então atualizar só esses
    dois campos aqui.
    """
    delivery = Delivery.objects.select_related('offer', 'social_channel').get(pk=delivery_id)

    if delivery.delivery_status == Delivery.DeliveryStatus.SENT:
        if delivery.next_retry_at is not None:
            delivery.next_retry_at = None
            delivery.save(update_fields=['next_retry_at', 'updated_at'])
        return RetryOutcome(
            delivery_id=delivery.id,
            offer_id=delivery.offer_id,
            channel_code=delivery.social_channel.code,
            status=OUTCOME_SENT,
        )

    if delivery.delivery_status in (Delivery.DeliveryStatus.PENDING, Delivery.DeliveryStatus.SKIPPED):
        # PENDING: outro processo está com a reserva em andamento (concorrência).
        # SKIPPED: caiu na janela de silêncio durante esta tentativa — não é
        # falha do item, então não consome tentativa; volta a ser candidato
        # normal (fora da fila) quando alguém tentar de novo.
        return RetryOutcome(
            delivery_id=delivery.id,
            offer_id=delivery.offer_id,
            channel_code=delivery.social_channel.code,
            status=OUTCOME_SKIPPED_EXTERNAL,
            detail=f'delivery_status={delivery.delivery_status} após a tentativa.',
        )

    return _handle_failed_attempt(delivery_id)


def _handle_failed_attempt(delivery_id: int) -> RetryOutcome:
    delivery = Delivery.objects.select_related('offer', 'social_channel').get(pk=delivery_id)

    max_retries = get_max_retries()
    delivery.retry_count += 1

    if delivery.retry_count >= max_retries:
        original_reason = delivery.error_message
        delivery.delivery_status = Delivery.DeliveryStatus.DEAD_LETTER
        delivery.error_message = (
            f'[dead-letter após {delivery.retry_count} tentativa(s)] {original_reason}'.strip()
        )
        delivery.next_retry_at = None
        delivery.save(
            update_fields=['retry_count', 'delivery_status', 'error_message', 'next_retry_at', 'updated_at'],
        )
        log.error(
            'fila_envio.dead_letter delivery_id=%s offer_id=%s channel=%s motivo=%s',
            delivery.id, delivery.offer_id, delivery.social_channel.code, original_reason,
        )
        enviar_alerta_operador(
            f'Entrega #{delivery.id} (oferta {delivery.offer_id}, canal '
            f'"{delivery.social_channel.code}") esgotou {delivery.retry_count} tentativas e foi '
            f'para dead-letter. Motivo original: {original_reason}',
            categoria='fila_envio_dead_letter',
        )
        outcome_status = OUTCOME_DEAD_LETTER
    else:
        delay_minutes = min(BACKOFF_BASE_MINUTES ** delivery.retry_count, BACKOFF_CAP_MINUTES)
        delivery.next_retry_at = timezone.now() + timedelta(minutes=delay_minutes)
        delivery.save(update_fields=['retry_count', 'next_retry_at', 'updated_at'])
        log.info(
            'fila_envio.retry_agendado delivery_id=%s offer_id=%s tentativa=%s/%s '
            'proxima_tentativa_em=%s',
            delivery.id, delivery.offer_id, delivery.retry_count, max_retries, delivery.next_retry_at,
        )
        outcome_status = OUTCOME_RETRY_SCHEDULED

    return RetryOutcome(
        delivery_id=delivery.id,
        offer_id=delivery.offer_id,
        channel_code=delivery.social_channel.code,
        status=outcome_status,
        detail=delivery.error_message,
    )
