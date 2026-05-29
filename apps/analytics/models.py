from django.db import models

from apps._base.models import TimestampedModel
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


class ClickEvent(TimestampedModel):
    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.PROTECT,
        related_name='click_events',
    )
    social_channel = models.ForeignKey(
        SocialChannel,
        verbose_name='canal social',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='click_events',
    )
    utm_source = models.CharField(
        'UTM source',
        max_length=80,
    )
    utm_medium = models.CharField(
        'UTM medium',
        max_length=80,
    )
    utm_campaign = models.CharField(
        'UTM campaign',
        max_length=120,
    )
    utm_content = models.CharField(
        'UTM content',
        max_length=120,
        blank=True,
    )
    clicked_at = models.DateTimeField(
        'clicado em',
    )
    user_agent = models.TextField(
        'user agent',
        blank=True,
    )
    ip_hash = models.CharField(
        'hash do IP',
        max_length=64,
        blank=True,
    )

    class Meta:
        ordering = ['-clicked_at']
        indexes = [
            models.Index(fields=['offer', 'clicked_at']),
            models.Index(fields=['social_channel', 'clicked_at']),
            models.Index(fields=['utm_source', 'clicked_at']),
            models.Index(fields=['utm_campaign']),
        ]
        verbose_name = 'evento de clique'
        verbose_name_plural = 'eventos de clique'

    def __str__(self):
        return f'{self.offer} — {self.utm_source}/{self.utm_medium} — {self.clicked_at}'
