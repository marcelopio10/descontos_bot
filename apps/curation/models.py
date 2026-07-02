from django.db import models

from apps._base.models import TimestampedModel
from apps.distribution.models import Delivery, SocialChannel
from apps.offers.models import Offer


class CurationRun(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        RUNNING = 'running', 'Em execução'
        COMPLETED = 'completed', 'Concluída'
        FAILED = 'failed', 'Falhou'
        CANCELLED = 'cancelled', 'Cancelada'

    class Mode(models.TextChoices):
        SHADOW = 'shadow', 'Shadow'
        DRY_RUN = 'dry_run', 'Dry-run'
        HOMOLOG = 'homolog', 'Homologação'
        PRODUCTION = 'production', 'Produção'

    channel = models.ForeignKey(
        SocialChannel,
        verbose_name='canal',
        on_delete=models.PROTECT,
        related_name='curation_runs',
    )
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.PENDING)
    mode = models.CharField('modo', max_length=20, choices=Mode.choices, default=Mode.DRY_RUN)
    profile_name = models.CharField('profile Hermes', max_length=120, blank=True)
    model_provider = models.CharField('provider do modelo', max_length=120, blank=True)
    model_name = models.CharField('modelo', max_length=160, blank=True)
    candidate_count = models.PositiveIntegerField('candidatas', default=0)
    selected_count = models.PositiveIntegerField('selecionadas', default=0)
    target_distribution_json = models.JSONField('distribuição alvo', default=dict, blank=True)
    actual_distribution_json = models.JSONField('distribuição real', default=dict, blank=True)
    observer_context_json = models.JSONField('contexto observer', default=dict, blank=True)
    baseline_summary_json = models.JSONField('baseline', default=dict, blank=True)
    input_json_path = models.CharField('JSON de entrada', max_length=500, blank=True)
    output_json_path = models.CharField('JSON de saída', max_length=500, blank=True)
    public_json_path = models.CharField('JSON público', max_length=500, blank=True)
    error_message = models.TextField('erro', blank=True)
    schema_version = models.CharField('versão schema', max_length=20, default='1.0')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['channel', 'status', 'mode']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'execução de curadoria IA'
        verbose_name_plural = 'execuções de curadoria IA'

    def __str__(self) -> str:
        return f'Curadoria {self.channel.code} #{self.pk} ({self.status})'


class CurationDecision(TimestampedModel):
    class Classification(models.TextChoices):
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Rejeitada'
        IMPROPER = 'improper', 'Imprópria'
        NEEDS_IMAGE_REVIEW = 'needs_image_review', 'Requer análise de imagem'

    run = models.ForeignKey(
        CurationRun,
        verbose_name='execução',
        on_delete=models.CASCADE,
        related_name='decisions',
    )
    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.PROTECT,
        related_name='curation_decisions',
    )
    marketplace_code = models.CharField('marketplace', max_length=64, blank=True)
    baseline_score = models.DecimalField('score baseline', max_digits=6, decimal_places=2, null=True, blank=True)
    baseline_classification = models.CharField('classificação baseline', max_length=60, blank=True)
    baseline_decision = models.CharField('decisão baseline', max_length=60, blank=True)
    ai_score = models.DecimalField('score IA', max_digits=6, decimal_places=2, null=True, blank=True)
    ai_classification = models.CharField(
        'classificação IA',
        max_length=30,
        choices=Classification.choices,
        default=Classification.REJECTED,
    )
    conversion_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    relevance_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    discount_quality_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    audience_fit_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    image_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    decision_reason = models.TextField('motivo', blank=True)
    risk_flags_json = models.JSONField('riscos', default=list, blank=True)
    observer_signals_json = models.JSONField('sinais observer', default=dict, blank=True)
    title_original = models.CharField('título original', max_length=500, blank=True)
    title_rewritten = models.CharField('título reescrito', max_length=500, blank=True)
    caption_rewritten = models.TextField('caption reescrita', blank=True)
    image_analysis_json = models.JSONField('análise de imagem', default=dict, blank=True)
    blacklist_terms_json = models.JSONField('termos blacklist', default=list, blank=True)
    raw_ai_json = models.JSONField('JSON bruto IA', default=dict, blank=True)
    is_selected_for_batch = models.BooleanField('selecionada para lote', default=False)

    class Meta:
        ordering = ['run', '-is_selected_for_batch', '-ai_score', 'offer_id']
        constraints = [
            models.UniqueConstraint(fields=['run', 'offer'], name='unique_curation_decision_run_offer'),
        ]
        indexes = [
            models.Index(fields=['run', 'ai_classification', 'is_selected_for_batch']),
            models.Index(fields=['offer', 'created_at']),
        ]
        verbose_name = 'decisão de curadoria IA'
        verbose_name_plural = 'decisões de curadoria IA'

    def __str__(self) -> str:
        return f'{self.offer_id} em {self.run_id}: {self.ai_classification}'


class CuratedBatch(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        READY = 'ready', 'Pronto'
        CONSUMING = 'consuming', 'Consumindo'
        SENT = 'sent', 'Enviado'
        EXPIRED = 'expired', 'Expirado'
        FAILED = 'failed', 'Falhou'

    run = models.OneToOneField(
        CurationRun,
        verbose_name='execução',
        on_delete=models.CASCADE,
        related_name='batch',
    )
    channel = models.ForeignKey(
        SocialChannel,
        verbose_name='canal',
        on_delete=models.PROTECT,
        related_name='curated_batches',
    )
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.DRAFT)
    batch_size = models.PositiveIntegerField('tamanho do lote', default=0)
    target_distribution_json = models.JSONField('distribuição alvo', default=dict, blank=True)
    actual_distribution_json = models.JSONField('distribuição real', default=dict, blank=True)
    expires_at = models.DateTimeField('expira em', null=True, blank=True)
    consumed_at = models.DateTimeField('consumido em', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['channel', 'status', 'expires_at']),
        ]
        verbose_name = 'lote curado'
        verbose_name_plural = 'lotes curados'

    def __str__(self) -> str:
        return f'Lote {self.channel.code} #{self.pk} ({self.status})'


class CuratedBatchItem(TimestampedModel):
    class SendStatus(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        SENT = 'sent', 'Enviado'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Ignorado'

    batch = models.ForeignKey(
        CuratedBatch,
        verbose_name='lote',
        on_delete=models.CASCADE,
        related_name='items',
    )
    decision = models.OneToOneField(
        CurationDecision,
        verbose_name='decisão',
        on_delete=models.PROTECT,
        related_name='batch_item',
    )
    offer = models.ForeignKey(
        Offer,
        verbose_name='oferta',
        on_delete=models.PROTECT,
        related_name='curated_batch_items',
    )
    position = models.PositiveIntegerField('posição')
    final_title = models.CharField('título final', max_length=500)
    final_caption_whatsapp = models.TextField('caption WhatsApp', blank=True)
    final_caption_telegram = models.TextField('caption Telegram', blank=True)
    final_image_url = models.URLField('URL imagem final', max_length=1200, blank=True)
    local_image_path = models.CharField('imagem local', max_length=500, blank=True)
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)
    image_mime_type = models.CharField(max_length=80, blank=True)
    send_status = models.CharField(max_length=20, choices=SendStatus.choices, default=SendStatus.PENDING)
    delivery = models.ForeignKey(
        Delivery,
        verbose_name='entrega',
        on_delete=models.SET_NULL,
        related_name='curated_batch_items',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['batch', 'position']
        constraints = [
            models.UniqueConstraint(fields=['batch', 'position'], name='unique_curated_batch_position'),
            models.UniqueConstraint(fields=['batch', 'offer'], name='unique_curated_batch_offer'),
        ]
        indexes = [
            models.Index(fields=['batch', 'send_status']),
        ]
        verbose_name = 'item de lote curado'
        verbose_name_plural = 'itens de lote curado'

    def __str__(self) -> str:
        return f'{self.batch_id}#{self.position} offer={self.offer_id}'


class CurationBlacklistTerm(TimestampedModel):
    class Source(models.TextChoices):
        AI_IMAGE_MODERATION = 'ai_image_moderation', 'Moderação IA de imagem'
        AI_TEXT_MODERATION = 'ai_text_moderation', 'Moderação IA de texto'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        ROLLED_BACK = 'rolled_back', 'Revertido'

    term = models.CharField('termo', max_length=160)
    normalized_term = models.CharField('termo normalizado', max_length=160, db_index=True)
    source = models.CharField('origem', max_length=40, choices=Source.choices)
    offer = models.ForeignKey(Offer, on_delete=models.SET_NULL, related_name='curation_blacklist_terms', null=True, blank=True)
    decision = models.ForeignKey(CurationDecision, on_delete=models.SET_NULL, related_name='blacklist_terms', null=True, blank=True)
    run = models.ForeignKey(CurationRun, on_delete=models.SET_NULL, related_name='blacklist_terms', null=True, blank=True)
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.ACTIVE)
    added_to_setting_at = models.DateTimeField('adicionado ao Setting em', null=True, blank=True)
    rolled_back_at = models.DateTimeField('rollback em', null=True, blank=True)
    rollback_reason = models.TextField('motivo rollback', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['normalized_term', 'status'], name='unique_curation_blacklist_term_status'),
        ]
        indexes = [
            models.Index(fields=['status', 'source']),
        ]
        verbose_name = 'termo automático de blacklist'
        verbose_name_plural = 'termos automáticos de blacklist'

    def __str__(self) -> str:
        return f'{self.term} ({self.status})'
