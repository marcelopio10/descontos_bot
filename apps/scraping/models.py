from django.db import models

from apps._base.models import TimestampedModel
from apps.marketplaces.models import Marketplace


class ScrapingRun(TimestampedModel):
    class RunStatus(models.TextChoices):
        RUNNING = 'running', 'Em execução'
        SUCCESS = 'success', 'Sucesso'
        PARTIAL_FAILED = 'partial_failed', 'Falha parcial'
        FAILED = 'failed', 'Falhou'

    marketplace = models.ForeignKey(
        Marketplace,
        verbose_name='marketplace',
        on_delete=models.PROTECT,
        related_name='scraping_runs',
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField(
        'iniciado em',
    )
    finished_at = models.DateTimeField(
        'finalizado em',
        null=True,
        blank=True,
    )
    status = models.CharField(
        'status',
        max_length=30,
        choices=RunStatus.choices,
        default=RunStatus.RUNNING,
    )
    total_collected = models.PositiveIntegerField(
        'total coletado',
        default=0,
    )
    total_valid = models.PositiveIntegerField(
        'total válido',
        default=0,
    )
    error_message = models.TextField(
        'mensagem de erro',
        blank=True,
    )

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['status', 'started_at']),
            models.Index(fields=['marketplace', 'started_at']),
        ]
        verbose_name = 'execução de coleta'
        verbose_name_plural = 'execuções de coleta'

    def __str__(self):
        marketplace = self.marketplace.name if self.marketplace else 'geral'
        return f'{marketplace} - {self.started_at:%d/%m/%Y %H:%M}'
