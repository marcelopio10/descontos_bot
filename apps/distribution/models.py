from django.db import models

from apps._base.models import TimestampedModel
from apps.offers.models import Offer


class SocialChannel(TimestampedModel):
    class ChannelType(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        WHATSAPP_GROUP = 'whatsapp_group', 'Grupo de WhatsApp'
        WHATSAPP_CHANNEL = 'whatsapp_channel', 'Canal do WhatsApp'
        TELEGRAM_CHANNEL = 'telegram_channel', 'Canal do Telegram'

    class LinkStrategy(models.TextChoices):
        AFFILIATE_DIRECT = 'affiliate_direct', 'Afiliado direto'
        BRIDGE_ONLY = 'bridge_only', 'Página pública'

    name = models.CharField(
        'nome',
        max_length=120,
    )
    code = models.SlugField(
        'código',
        max_length=60,
        unique=True,
    )
    channel_type = models.CharField(
        'tipo de canal',
        max_length=30,
        choices=ChannelType.choices,
        default=ChannelType.WHATSAPP,
    )
    target = models.CharField(
        'destino',
        max_length=255,
        help_text='Nome exato do grupo ou identificador usado pelo serviço de envio.',
    )
    is_enabled = models.BooleanField(
        'habilitado',
        default=True,
    )
    link_strategy = models.CharField(
        'estratégia de link',
        max_length=20,
        choices=LinkStrategy.choices,
        default=LinkStrategy.BRIDGE_ONLY,
        help_text='Use página pública para canais privados. Afiliado direto somente para fontes cadastradas na Amazon.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'canal social'
        verbose_name_plural = 'canais sociais'

    def __str__(self):
        return self.name


class Delivery(TimestampedModel):
    class DeliveryStatus(models.TextChoices):
        PENDING = 'pending', 'Em envio'
        SENT = 'sent', 'Enviado'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Ignorado'

    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.PROTECT,
        related_name='deliveries',
    )
    social_channel = models.ForeignKey(
        SocialChannel,
        verbose_name='canal social',
        on_delete=models.PROTECT,
        related_name='deliveries',
    )
    message = models.TextField(
        'mensagem',
    )
    delivery_status = models.CharField(
        'status do envio',
        max_length=20,
        choices=DeliveryStatus.choices,
    )
    external_message_id = models.CharField(
        'ID externo da mensagem',
        max_length=160,
        blank=True,
    )
    error_message = models.TextField(
        'mensagem de erro',
        blank=True,
    )
    sent_at = models.DateTimeField(
        'enviado em',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['offer', 'social_channel'],
                name='unique_delivery_offer_social_channel',
            ),
        ]
        indexes = [
            models.Index(fields=['delivery_status', 'sent_at']),
            models.Index(fields=['social_channel', 'delivery_status']),
        ]
        verbose_name = 'entrega'
        verbose_name_plural = 'entregas'

    def __str__(self):
        return f'{self.offer} -> {self.social_channel}'
