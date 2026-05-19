import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.curation.services.telegram_message_builder import (
    TelegramMessagePayload,
    build_telegram_payload,
)
from apps.distribution.models import Delivery, SocialChannel
from apps.distribution.services.execution_window import (
    get_silence_error_message,
    is_distribution_silenced,
)
from apps.distribution.services.telegram_client import (
    TelegramClient,
    TelegramClientError,
    TelegramSendResult,
)
from apps.distribution.services.telegram_rate_limiter import (
    TelegramRateLimiter,
    get_default_limiter,
)
from apps.offers.models import Offer


logger = logging.getLogger('apps.distribution.telegram')


@dataclass(frozen=True)
class TelegramDeliveryResult:
    delivery: Delivery
    sent: bool


def deliver_offer_to_telegram(
    offer: Offer,
    channel: SocialChannel,
    client: TelegramClient | None = None,
    rate_limiter: TelegramRateLimiter | None = None,
) -> TelegramDeliveryResult:
    payload = build_telegram_payload(offer, channel)

    existing_delivery = Delivery.objects.filter(
        offer=offer,
        social_channel=channel,
    ).first()
    if (
        existing_delivery
        and existing_delivery.delivery_status == Delivery.DeliveryStatus.SENT
    ):
        logger.info(
            'telegram.send.skipped offer_id=%s channel=%s reason=already_sent',
            offer.id, channel.code,
        )
        return TelegramDeliveryResult(delivery=existing_delivery, sent=False)

    if is_distribution_silenced():
        logger.info(
            'telegram.send.silence offer_id=%s channel=%s reason=window',
            offer.id, channel.code,
        )
        delivery = _save_delivery(
            existing_delivery=existing_delivery,
            offer=offer,
            channel=channel,
            message=payload.caption,
            status=Delivery.DeliveryStatus.SKIPPED,
            error_message=get_silence_error_message(),
        )
        return TelegramDeliveryResult(delivery=delivery, sent=False)

    client = client or TelegramClient()
    limiter = rate_limiter or get_default_limiter()
    limiter.wait_for_send(channel.target)

    result = _try_send(client, channel.target, payload)
    fallback_used = False
    if payload.use_photo and not result.success:
        logger.warning(
            'telegram.fallback=text_only offer_id=%s channel=%s error=%s',
            offer.id, channel.code, result.error_message,
        )
        limiter.wait_for_send(channel.target)
        result = _send_text(client, channel.target, payload)
        fallback_used = True

    status = (
        Delivery.DeliveryStatus.SENT
        if result.success
        else Delivery.DeliveryStatus.FAILED
    )
    delivery = _save_delivery(
        existing_delivery=existing_delivery,
        offer=offer,
        channel=channel,
        message=payload.caption,
        status=status,
        external_message_id=result.message_id,
        error_message=result.error_message,
        sent_at=(result.sent_at or timezone.now()) if result.success else None,
    )

    if result.success:
        logger.info(
            'telegram.send.ok offer_id=%s channel=%s message_id=%s chat=%s '
            'route=affiliate_direct fallback=%s',
            offer.id, channel.code, result.message_id, channel.target, fallback_used,
        )
    else:
        logger.error(
            'telegram.send.failed offer_id=%s channel=%s error=%s',
            offer.id, channel.code, result.error_message,
        )

    return TelegramDeliveryResult(delivery=delivery, sent=result.success)


def _try_send(
    client: TelegramClient,
    chat_id: str,
    payload: TelegramMessagePayload,
) -> TelegramSendResult:
    try:
        if payload.use_photo:
            return client.send_photo(
                chat_id=chat_id,
                photo_url=payload.photo_url,
                caption_html=payload.caption,
                inline_keyboard=payload.inline_keyboard,
            )
        return _send_text(client, chat_id, payload)
    except TelegramClientError as exc:
        return TelegramSendResult(
            success=False,
            message_id='',
            sent_at=None,
            error_message=str(exc),
        )


def _send_text(
    client: TelegramClient,
    chat_id: str,
    payload: TelegramMessagePayload,
) -> TelegramSendResult:
    try:
        return client.send_message(
            chat_id=chat_id,
            text_html=payload.caption,
            inline_keyboard=payload.inline_keyboard,
            disable_web_page_preview=True,
        )
    except TelegramClientError as exc:
        return TelegramSendResult(
            success=False,
            message_id='',
            sent_at=None,
            error_message=str(exc),
        )


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
