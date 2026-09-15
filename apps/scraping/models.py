from django.db import models

from apps._base.models import TimestampedModel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


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
    provider = models.CharField(
        'provider de coleta',
        max_length=60,
        default='legacy_scraper',
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


class ScrapingItemResult(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        ACCEPTED = 'accepted', 'Aceito'
        DISCARDED = 'discarded', 'Descartado'
        AFFILIATE_FAILED = 'affiliate_failed', 'Afiliado com falha'
        FAILED = 'failed', 'Falhou'

    run = models.ForeignKey(
        ScrapingRun,
        verbose_name='execução',
        on_delete=models.CASCADE,
        related_name='item_results',
    )
    sequence = models.PositiveIntegerField('sequência')
    external_id = models.CharField('ID externo', max_length=160, blank=True)
    original_url = models.URLField('URL original', max_length=1200, blank=True)
    source = models.CharField('origem da busca', max_length=160, blank=True)
    status = models.CharField(
        'status do item',
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reason_code = models.CharField('código do motivo', max_length=100, blank=True)
    error_message = models.TextField('erro', blank=True)
    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scraping_results',
    )
    processed_at = models.DateTimeField('processado em')

    class Meta:
        ordering = ['run', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'sequence'],
                name='unique_scraping_item_result_sequence',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'processed_at']),
            models.Index(fields=['external_id']),
        ]
        verbose_name = 'resultado de item coletado'
        verbose_name_plural = 'resultados de itens coletados'

    def __str__(self):
        return f'{self.run_id}:{self.sequence} {self.external_id or "sem-id"}'
