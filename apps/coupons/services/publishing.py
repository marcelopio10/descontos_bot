from __future__ import annotations

from django.utils import timezone

from apps.distribution.services.execution_window import get_silence_error_message, is_distribution_silenced
from apps.distribution.services.telegram_client import TelegramClient, TelegramClientError
from apps.distribution.services.whatsapp_client import WhatsAppClient, WhatsAppClientError

from .links import build_coupon_link
from ..models import CouponDelivery
from .posts import build_coupon_post, build_coupon_telegram_post
from .validation import final_validate


def publish_coupon(candidate, channel, *, whatsapp_client=None, telegram_client=None):
    prior_hash = CouponDelivery.objects.filter(
        candidate__candidate_hash=candidate.candidate_hash,
        status='sent',
    ).exclude(candidate=candidate).exists()
    validation = final_validate(
        {
            'candidate_hash': candidate.candidate_hash,
            'marketplace': candidate.marketplace,
            'activation_code': candidate.activation_code,
            'activation_method': candidate.activation_method,
            'benefit': candidate.benefit,
            'source_url': candidate.source_url,
            'destination_url': candidate.destination_url,
            'evidence': candidate.evidence,
            'valid_until': candidate.valid_until,
        },
        candidate.affiliate_url,
        {candidate.candidate_hash} if prior_hash else set(),
    )
    message = build_coupon_telegram_post(candidate, channel) if channel.channel_type == 'telegram_channel' else build_coupon_post(candidate, channel)
    delivery, created = CouponDelivery.objects.get_or_create(
        candidate=candidate, channel=channel,
        defaults={'message': message, 'published_url': build_coupon_link(candidate, channel), 'affiliate_used': bool(candidate.affiliate_url)},
    )
    if not validation.accepted:
        delivery.status = 'skipped'
        delivery.error_message = validation.reason
        delivery.save(update_fields=['status', 'error_message', 'updated_at'])
        return delivery
    if not created and delivery.status == 'sent':
        return delivery
    if is_distribution_silenced():
        delivery.status, delivery.error_message = 'skipped', get_silence_error_message()
        delivery.save(update_fields=['status', 'error_message', 'updated_at'])
        return delivery
    try:
        if channel.channel_type == 'telegram_channel':
            client = telegram_client or TelegramClient()
            result = client.send_message(chat_id=channel.target, text_html=message, inline_keyboard=[[{'text': 'Usar cupom', 'url': build_coupon_link(candidate, channel)}]], disable_web_page_preview=True)
        else:
            client = whatsapp_client or WhatsAppClient()
            status = client.get_status()
            if not status.connected:
                raise WhatsAppClientError('WhatsApp não conectado')
            result = client.send_message(channel.target, message, '')
        delivery.status = 'sent' if result.success else 'failed'
        delivery.external_message_id = result.message_id or ''
        delivery.error_message = result.error_message or ''
        delivery.sent_at = timezone.now() if result.success else None
    except (WhatsAppClientError, TelegramClientError, Exception) as exc:
        delivery.status = 'failed'
        delivery.error_message = str(exc)[:2000]
    delivery.save(update_fields=['status', 'external_message_id', 'error_message', 'sent_at', 'updated_at'])
    return delivery
