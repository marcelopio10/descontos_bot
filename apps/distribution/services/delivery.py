from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.curation.services.message_builder import build_offer_message
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)
from apps.distribution.services.whatsapp_client import WhatsAppClient, WhatsAppClientError
from apps.offers.models import Offer


@dataclass(frozen=True)
class DeliveryResult:
    delivery: Delivery
    sent: bool


def deliver_offer_to_channel(
    offer: Offer,
    channel: SocialChannel,
    client: WhatsAppClient | None = None,
) -> DeliveryResult:
    message = build_offer_message(offer)

    existing_delivery = Delivery.objects.filter(
        offer=offer,
        social_channel=channel,
    ).first()
    if (
        existing_delivery
        and existing_delivery.delivery_status == Delivery.DeliveryStatus.SENT
    ):
        return DeliveryResult(delivery=existing_delivery, sent=False)

    if is_distribution_silenced():
        delivery = _save_delivery(
            existing_delivery=existing_delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.SKIPPED,
            error_message=get_silence_error_message(),
        )
        return DeliveryResult(delivery=delivery, sent=False)

    client = client or WhatsAppClient()

    try:
        status = client.get_status()
        if not status.connected:
            delivery = _save_delivery(
                existing_delivery=existing_delivery,
                offer=offer,
                channel=channel,
                message=message,
                status=Delivery.DeliveryStatus.FAILED,
                error_message='WhatsApp não conectado. Pareie a sessão no wa_service.',
            )
            return DeliveryResult(delivery=delivery, sent=False)

        result = client.send_message(channel.target, message, offer.image_url)
    except WhatsAppClientError as exc:
        delivery = _save_delivery(
            existing_delivery=existing_delivery,
            offer=offer,
            channel=channel,
            message=message,
            status=Delivery.DeliveryStatus.FAILED,
            error_message=str(exc),
        )
        return DeliveryResult(delivery=delivery, sent=False)

    status = Delivery.DeliveryStatus.SENT if result.success else Delivery.DeliveryStatus.FAILED
    delivery = _save_delivery(
        existing_delivery=existing_delivery,
        offer=offer,
        channel=channel,
        message=message,
        status=status,
        external_message_id=result.message_id,
        error_message=result.error_message,
        sent_at=(result.sent_at or timezone.now()) if result.success else None,
    )
    return DeliveryResult(delivery=delivery, sent=result.success)


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
