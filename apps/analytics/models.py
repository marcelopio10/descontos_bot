from django.db import models

from apps._base.models import TimestampedModel
from apps.distribution.models import SocialChannel
from apps.offers.models import Offer


class AffiliateSource(models.TextChoices):
    AMAZON = 'amazon', 'Amazon Associates'
    MERCADO_LIVRE = 'mercado_livre', 'Mercado Livre Afiliados'
    SHOPEE = 'shopee', 'Shopee Afiliados'


class AffiliateImportBatch(TimestampedModel):
    source = models.CharField(
        'fonte',
        max_length=32,
        choices=AffiliateSource.choices,
        db_index=True,
    )
    period_start = models.DateField(
        'início do período',
        null=True,
        blank=True,
    )
    period_end = models.DateField(
        'fim do período',
        null=True,
        blank=True,
    )
    raw_filename = models.CharField(
        'arquivo original',
        max_length=255,
        blank=True,
    )
    payload_sha256 = models.CharField(
        'sha256 do payload',
        max_length=64,
        db_index=True,
    )
    rows_imported = models.PositiveIntegerField(
        'linhas importadas',
        default=0,
    )
    rows_skipped = models.PositiveIntegerField(
        'linhas ignoradas',
        default=0,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'lote de importação de afiliados'
        verbose_name_plural = 'lotes de importação de afiliados'

    def __str__(self):
        return f'{self.get_source_display()} — {self.created_at:%Y-%m-%d %H:%M}'


class AffiliateConversion(TimestampedModel):
    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affiliate_conversions',
    )
    social_channel = models.ForeignKey(
        SocialChannel,
        verbose_name='canal social',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='affiliate_conversions',
    )
    source = models.CharField(
        'fonte',
        max_length=32,
        choices=AffiliateSource.choices,
        db_index=True,
    )
    external_ref = models.CharField(
        'referência externa (ASIN/MLB)',
        max_length=64,
        blank=True,
        db_index=True,
    )
    product_title = models.CharField(
        'título do produto (relatório)',
        max_length=255,
        blank=True,
    )
    period_start = models.DateField(
        'início do período',
        db_index=True,
    )
    period_end = models.DateField(
        'fim do período',
        db_index=True,
    )
    clicks = models.PositiveIntegerField(
        'cliques',
        default=0,
    )
    conversions = models.PositiveIntegerField(
        'conversões',
        default=0,
    )
    revenue_brl = models.DecimalField(
        'receita (R$)',
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    commission_brl = models.DecimalField(
        'comissão (R$)',
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    batch = models.ForeignKey(
        AffiliateImportBatch,
        verbose_name='lote',
        on_delete=models.CASCADE,
        related_name='conversions',
    )

    class Meta:
        ordering = ['-period_end', '-commission_brl']
        constraints = [
            models.UniqueConstraint(
                fields=['offer', 'source', 'period_start', 'period_end'],
                condition=models.Q(offer__isnull=False),
                name='uniq_affconv_with_offer',
            ),
            models.UniqueConstraint(
                fields=['external_ref', 'source', 'period_start', 'period_end'],
                condition=models.Q(offer__isnull=True),
                name='uniq_affconv_no_offer',
            ),
        ]
        indexes = [
            models.Index(fields=['source', 'period_end']),
            models.Index(fields=['social_channel', 'period_end']),
        ]
        verbose_name = 'conversão de afiliado'
        verbose_name_plural = 'conversões de afiliados'

    def __str__(self):
        ref = self.offer or self.external_ref or '—'
        return (
            f'{ref} — {self.get_source_display()} — '
            f'{self.period_start}..{self.period_end} — R$ {self.commission_brl}'
        )


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
