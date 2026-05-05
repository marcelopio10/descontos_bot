from django.db import models

from apps._base.models import TimestampedModel
from apps.marketplaces.models import Marketplace


class Offer(TimestampedModel):
    marketplace = models.ForeignKey(
        Marketplace,
        verbose_name='marketplace',
        on_delete=models.PROTECT,
        related_name='offers',
    )
    external_id = models.CharField(
        'ID externo',
        max_length=160,
        blank=True,
    )
    title = models.CharField(
        'título',
        max_length=500,
    )
    normalized_title = models.CharField(
        'título normalizado',
        max_length=500,
    )
    offer_hash = models.CharField(
        'hash da oferta',
        max_length=64,
        unique=True,
    )
    current_price = models.DecimalField(
        'preço atual',
        max_digits=12,
        decimal_places=2,
    )
    original_price = models.DecimalField(
        'preço original',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount_pct = models.DecimalField(
        'desconto (%)',
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    product_url = models.URLField(
        'URL do produto',
        max_length=1200,
    )
    affiliate_url = models.URLField(
        'URL de afiliado',
        max_length=1200,
        blank=True,
    )
    image_url = models.URLField(
        'URL da imagem',
        max_length=1200,
        blank=True,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )
    raw_payload = models.JSONField(
        'payload bruto',
        default=dict,
        blank=True,
    )
    first_seen_at = models.DateTimeField(
        'visto primeiro em',
    )
    last_seen_at = models.DateTimeField(
        'visto por último em',
    )

    class Meta:
        ordering = ['-discount_pct', 'title']
        indexes = [
            models.Index(fields=['offer_hash']),
            models.Index(fields=['marketplace', 'external_id']),
            models.Index(fields=['is_active', 'discount_pct']),
            models.Index(fields=['last_seen_at']),
        ]
        verbose_name = 'oferta'
        verbose_name_plural = 'ofertas'

    def __str__(self):
        return self.title
