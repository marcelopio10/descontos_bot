from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem
from apps.curation.services.message_builder import build_curated_offer_message, build_offer_message
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)
from apps.distribution.services.whatsapp_client import (
    WhatsAppClient,
    WhatsAppClientError,
    WhatsAppStatus,
)
from apps.distribution.services.whatsapp_rate_limiter import (
    WhatsAppRateLimiter,
    get_default_limiter as get_default_whatsapp_rate_limiter,
)
from apps.offers.models import Offer

PENDING_STALE_AFTER = timedelta(minutes=15)
REPUBLISH_COOLDOWN = timedelta(hours=12)
REPUBLISH_MIN_PRICE_DROP = Decimal('0.10')
PRICE_RE = re.compile(r'R\$\s*([0-9.]+,[0-9]{2}|[0-9]+(?:\.[0-9]{2})?)', re.IGNORECASE)


class SessaoIndisponivelError(Exception):
    """Levantada quando a sessão do WhatsApp cai durante o envio de um lote.

    Distinta de uma falha pontual de uma oferta específica: sinaliza ao
    chamador (loops de `run_bot`) que a sessão está indisponível e o restante
    do lote deve ser interrompido (break), em vez de continuar tentando enviar
    e marcando cada oferta seguinte como FAILED individualmente (achado C3).
    A oferta que estava em processamento no momento da queda já foi salva
    (normalmente como FAILED) antes desta exceção ser levantada.
    """


@dataclass(frozen=True)
class DeliveryResult:
    delivery: Delivery
    sent: bool


def get_whatsapp_session_status(client: WhatsAppClient | None = None) -> WhatsAppStatus:
    """Consulta o status da sessão do WhatsApp usando o mesmo `WhatsAppClient`
    dos caminhos de envio (`deliver_offer_to_channel`/`deliver_curated_item_to_whatsapp`).

    Existe para que o pre-check de sessão do `run_bot` (Tarefa 1.3, antes do
    loop de envio) reutilize a mesma fábrica de client deste módulo — inclusive
    em testes, que fazem `patch('apps.distribution.services.delivery.WhatsAppClient', ...)`.
    Levanta `WhatsAppClientError` se a consulta falhar (adapter indisponível).
    """
    client = client or WhatsAppClient()
    return client.get_status()


def deliver_offer_to_channel(
    offer: Offer,
    channel: SocialChannel,
    client: WhatsAppClient | None = None,
    rate_limiter: WhatsAppRateLimiter | None = None,
) -> DeliveryResult:
    message = build_offer_message(offer, channel)

    if is_distribution_silenced():
        existing_delivery = Delivery.objects.filter(
            offer=offer,
            social_channel=channel,
        ).first()
        delivery = _save_delivery(
            existing_delivery=existing_delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.SKIPPED,
            error_message=get_silence_error_message(),
        )
        return DeliveryResult(delivery=delivery, sent=False)

    delivery, should_send = _reserve_delivery_for_send(
        offer=offer,
        channel=channel,
        message=message,
    )
    if not should_send:
        return DeliveryResult(delivery=delivery, sent=False)

    client = client or WhatsAppClient()

    try:
        status = client.get_status()
        if not status.connected:
            delivery = _save_delivery(
                existing_delivery=delivery,
                offer=offer,
                channel=channel,
                message=message,
                status=Delivery.DeliveryStatus.FAILED,
                error_message='WhatsApp não conectado. Verifique a sessão do provedor configurado.',
            )
            raise SessaoIndisponivelError(
                'WhatsApp não conectado. Verifique a sessão do provedor configurado.',
            )

        limiter = rate_limiter or get_default_whatsapp_rate_limiter()
        limiter.wait_for_send(channel.target)

        result = client.send_message(channel.target, message, offer.image_url)
    except WhatsAppClientError as exc:
        delivery = _save_delivery(
            existing_delivery=delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.FAILED,
            error_message=str(exc),
        )
        raise SessaoIndisponivelError(str(exc)) from exc

    status = Delivery.DeliveryStatus.SENT if result.success else Delivery.DeliveryStatus.FAILED
    delivery = _save_delivery(
        existing_delivery=delivery,
        offer=offer,
        channel=channel,
        message=message,
        status=status,
        external_message_id=result.message_id,
        error_message=result.error_message,
        sent_at=(result.sent_at or timezone.now()) if result.success else None,
    )
    return DeliveryResult(delivery=delivery, sent=result.success)


def deliver_curated_item_to_whatsapp(
    item: CuratedBatchItem,
    channel: SocialChannel,
    client: WhatsAppClient | None = None,
    rate_limiter: WhatsAppRateLimiter | None = None,
) -> DeliveryResult:
    offer = item.offer
    message = build_curated_offer_message(item, channel).strip()
    image_url = (item.local_image_path or item.final_image_url or offer.image_url or '').strip()

    if is_distribution_silenced():
        existing_delivery = Delivery.objects.filter(
            offer=offer,
            social_channel=channel,
        ).first()
        delivery = _save_delivery(
            existing_delivery=existing_delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.SKIPPED,
            error_message=get_silence_error_message(),
        )
        mark_curated_item_delivery(item, delivery, CuratedBatchItem.SendStatus.SKIPPED)
        return DeliveryResult(delivery=delivery, sent=False)

    delivery, should_send = _reserve_delivery_for_send(
        offer=offer,
        channel=channel,
        message=message,
    )
    if not should_send:
        mark_curated_item_delivery(item, delivery, CuratedBatchItem.SendStatus.SKIPPED)
        return DeliveryResult(delivery=delivery, sent=False)

    client = client or WhatsAppClient()
    try:
        status = client.get_status()
        if not status.connected:
            delivery = _save_delivery(
                existing_delivery=delivery,
                offer=offer,
                channel=channel,
                message=message,
                status=Delivery.DeliveryStatus.FAILED,
                error_message='WhatsApp não conectado. Verifique a sessão do provedor configurado.',
            )
            mark_curated_item_delivery(item, delivery, CuratedBatchItem.SendStatus.FAILED)
            raise SessaoIndisponivelError(
                'WhatsApp não conectado. Verifique a sessão do provedor configurado.',
            )

        limiter = rate_limiter or get_default_whatsapp_rate_limiter()
        limiter.wait_for_send(channel.target)

        result = client.send_message(channel.target, message, image_url)
    except WhatsAppClientError as exc:
        delivery = _save_delivery(
            existing_delivery=delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.FAILED,
            error_message=str(exc),
        )
        mark_curated_item_delivery(item, delivery, CuratedBatchItem.SendStatus.FAILED)
        raise SessaoIndisponivelError(str(exc)) from exc

    status = Delivery.DeliveryStatus.SENT if result.success else Delivery.DeliveryStatus.FAILED
    delivery = _save_delivery(
        existing_delivery=delivery,
        offer=offer,
        channel=channel,
        message=message,
        status=status,
        external_message_id=result.message_id,
        error_message=result.error_message,
        sent_at=(result.sent_at or timezone.now()) if result.success else None,
    )
    mark_curated_item_delivery(
        item,
        delivery,
        CuratedBatchItem.SendStatus.SENT if result.success else CuratedBatchItem.SendStatus.FAILED,
    )
    return DeliveryResult(delivery=delivery, sent=result.success)


def mark_curated_item_delivery(
    item: CuratedBatchItem,
    delivery: Delivery,
    status: str,
) -> None:
    item.delivery = delivery
    item.send_status = status
    item.save(update_fields=['delivery', 'send_status', 'updated_at'])

    batch = item.batch
    statuses = list(batch.items.values_list('send_status', flat=True))
    if statuses and all(value == CuratedBatchItem.SendStatus.SENT for value in statuses):
        batch.status = CuratedBatch.Status.SENT
        batch.consumed_at = timezone.now()
        batch.save(update_fields=['status', 'consumed_at', 'updated_at'])
    elif any(value == CuratedBatchItem.SendStatus.FAILED for value in statuses):
        batch.status = CuratedBatch.Status.FAILED
        batch.save(update_fields=['status', 'updated_at'])


def _reserve_delivery_for_send(
    offer: Offer,
    channel: SocialChannel,
    message: str,
) -> tuple[Delivery, bool]:
    """Cria reserva antes do envio externo para evitar duplicidade no canal.

    A constraint única protege o banco, mas não protege o WhatsApp: dois processos
    simultâneos podiam selecionar a mesma oferta, enviar para o mesmo canal e só
    depois disputar a gravação da entrega. A reserva torna a decisão idempotente
    antes da chamada ao wa_service.
    """
    stale_cutoff = timezone.now() - PENDING_STALE_AFTER

    try:
        with transaction.atomic():
            delivery = (
                Delivery.objects.select_for_update()
                .filter(offer=offer, social_channel=channel)
                .first()
            )
            if delivery:
                if delivery.delivery_status == Delivery.DeliveryStatus.SENT:
                    if _should_republish_after_improvement(delivery, offer, message):
                        delivery.message = message
                        delivery.delivery_status = Delivery.DeliveryStatus.PENDING
                        delivery.external_message_id = ''
                        delivery.error_message = 'Reentrada por melhoria comercial.'
                        delivery.sent_at = None
                        delivery.save(update_fields=[
                            'message', 'delivery_status', 'external_message_id',
                            'error_message', 'sent_at', 'updated_at',
                        ])
                        return delivery, True
                    return delivery, False
                if (
                    delivery.delivery_status == Delivery.DeliveryStatus.PENDING
                    and delivery.updated_at >= stale_cutoff
                ):
                    return delivery, False

                delivery.message = message
                delivery.delivery_status = Delivery.DeliveryStatus.PENDING
                delivery.external_message_id = ''
                delivery.error_message = 'Envio em andamento.'
                delivery.sent_at = None
                delivery.save(
                    update_fields=[
                        'message',
                        'delivery_status',
                        'external_message_id',
                        'error_message',
                        'sent_at',
                        'updated_at',
                    ],
                )
                return delivery, True

            delivery = Delivery.objects.create(
                offer=offer,
                social_channel=channel,
                message=message,
                delivery_status=Delivery.DeliveryStatus.PENDING,
                error_message='Envio em andamento.',
            )
            return delivery, True
    except IntegrityError:
        delivery = Delivery.objects.get(offer=offer, social_channel=channel)
        if delivery.delivery_status == Delivery.DeliveryStatus.PENDING:
            return delivery, False
        return delivery, delivery.delivery_status != Delivery.DeliveryStatus.SENT


def _should_republish_after_improvement(delivery: Delivery, offer: Offer, message: str) -> bool:
    """Permite uma nova publicação somente por melhoria material e com cooldown."""
    if not delivery.sent_at or timezone.now() - delivery.sent_at < REPUBLISH_COOLDOWN:
        return False
    previous_price = _last_message_price(delivery.message)
    current_price = _last_message_price(message) or offer.current_price
    if previous_price is None or current_price is None or previous_price <= 0:
        return False
    drop = (previous_price - Decimal(current_price)) / previous_price
    return drop >= REPUBLISH_MIN_PRICE_DROP


def _last_message_price(message: str) -> Decimal | None:
    matches = PRICE_RE.findall(message or '')
    if not matches:
        return None
    raw = matches[-1].replace('.', '').replace(',', '.')
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _save_delivery(
    existing_delivery: Delivery | None,
    offer: Offer,
    channel: SocialChannel,
    message: str,
    status: str,
    external_message_id: str = '',
    error_message: str = '',
    sent_at=None,
) -> Delivery:
    if existing_delivery:
        existing_delivery.message = message
        existing_delivery.delivery_status = status
        existing_delivery.external_message_id = external_message_id
        existing_delivery.error_message = error_message
        existing_delivery.sent_at = sent_at
        existing_delivery.save(
            update_fields=[
                'message',
                'delivery_status',
                'external_message_id',
                'error_message',
                'sent_at',
                'updated_at',
            ],
        )
        return existing_delivery

    try:
        with transaction.atomic():
            return Delivery.objects.create(
                offer=offer,
                social_channel=channel,
                message=message,
                delivery_status=status,
                external_message_id=external_message_id,
                error_message=error_message,
                sent_at=sent_at,
            )
    except IntegrityError:
        return Delivery.objects.get(offer=offer, social_channel=channel)
