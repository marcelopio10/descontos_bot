from django.db import models

from apps._base.models import TimestampedModel


class Setting(TimestampedModel):
    key = models.SlugField(
        'chave',
        max_length=120,
        unique=True,
    )
    value = models.TextField(
        'valor',
    )
    description = models.TextField(
        'descrição',
        blank=True,
    )

    class Meta:
        ordering = ['key']
        verbose_name = 'configuração'
        verbose_name_plural = 'configurações'

    def __str__(self):
        return self.key
