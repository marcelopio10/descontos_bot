from django.db import models

from apps._base.models import TimestampedModel


class Marketplace(TimestampedModel):
    name = models.CharField(
        'nome',
        max_length=80,
    )
    code = models.SlugField(
        'código',
        max_length=40,
        unique=True,
    )
    base_url = models.URLField(
        'URL base',
        max_length=500,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )
    affiliate_enabled = models.BooleanField(
        'afiliado habilitado',
        default=False,
    )
    affiliate_tag = models.CharField(
        'tag de afiliado',
        max_length=50,
        blank=True,
        help_text='Tag usada para montar links canônicos de afiliado quando aplicável.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'marketplace'
        verbose_name_plural = 'marketplaces'

    def __str__(self):
        return self.name
