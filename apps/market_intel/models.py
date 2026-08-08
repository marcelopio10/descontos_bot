from django.db import models

from apps._base.models import TimestampedModel


class ObservedWhatsAppGroup(models.Model):
    name = models.CharField(max_length=255)
    jid = models.CharField(max_length=128, unique=True)
    is_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return f'{self.name} ({self.jid})'


class ObservedWhatsAppMessage(models.Model):
    group = models.ForeignKey(
        ObservedWhatsAppGroup,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    external_message_id = models.CharField(max_length=255)
    sender_hash = models.CharField(max_length=64)
    sent_at = models.DateTimeField()
    collected_at = models.DateTimeField()
    text = models.TextField()
    urls = models.JSONField(default=list, blank=True)
    has_image = models.BooleanField(default=False)
    raw_type = models.CharField(max_length=64, blank=True)

    # --- Campos existentes (v1) ---
    parsed_marketplace = models.CharField(max_length=64, blank=True)
    parsed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parsed_original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parsed_discount_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    parsed_coupon = models.CharField(max_length=80, blank=True)
    editorial_labels = models.JSONField(default=list, blank=True)
    scraper_hints = models.JSONField(default=list, blank=True)

    # --- P0-1: Sinais de engajamento (null para WhatsApp; preenchido para Telegram) ---
    reacoes = models.PositiveIntegerField(null=True, blank=True)
    visualizacoes = models.PositiveIntegerField(null=True, blank=True)
    encaminhamentos = models.PositiveIntegerField(null=True, blank=True)
    comentarios = models.PositiveIntegerField(null=True, blank=True)
    repostado = models.BooleanField(null=True, blank=True)
    qtd_repostagens = models.PositiveIntegerField(null=True, blank=True)
    fixado = models.BooleanField(null=True, blank=True)

    # --- P0-2: Mecânica de preço ---
    parcelamento = models.PositiveSmallIntegerField(null=True, blank=True)
    parcelado_sem_juros = models.BooleanField(null=True, blank=True)
    pix = models.BooleanField(null=True, blank=True)
    pix_desconto_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cashback = models.BooleanField(null=True, blank=True)
    cashback_valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    menor_preco = models.BooleanField(null=True, blank=True)
    cupom_tipo = models.CharField(max_length=20, blank=True)

    # --- P0-3: Padrões de copy e formato ---
    emoji_densidade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    emojis_top = models.JSONField(default=list, blank=True)
    tem_headline = models.BooleanField(null=True, blank=True)
    tem_de_por = models.BooleanField(null=True, blank=True)
    tem_cta = models.BooleanField(null=True, blank=True)
    cta_termos = models.JSONField(default=list, blank=True)
    tipo_midia = models.CharField(max_length=20, blank=True)
    tamanho_mensagem = models.PositiveIntegerField(null=True, blank=True)
    usa_caixa_alta = models.BooleanField(null=True, blank=True)
    usa_negrito = models.BooleanField(null=True, blank=True)

    # --- P1-5: Marketplace mais rico ---
    marketplace_dominio_desconhecido = models.CharField(max_length=500, blank=True)
    programa_entrega = models.CharField(max_length=20, blank=True)

    # --- P1-6: Marca dentro da categoria ---
    marca = models.CharField(max_length=80, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sent_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['group', 'external_message_id'],
                name='unique_observed_whatsapp_message',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.group.name} #{self.external_message_id}'


class MarketIntelDailyReport(models.Model):
    date = models.DateField(unique=True)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    groups_analyzed = models.PositiveIntegerField(default=0)
    messages_analyzed = models.PositiveIntegerField(default=0)
    summary_json = models.JSONField(default=dict, blank=True)
    recommendations_json = models.JSONField(default=list, blank=True)
    scraper_opportunities_json = models.JSONField(default=list, blank=True)
    payload_version = models.CharField(max_length=8, default='2.0')
    site_payload_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']

    def __str__(self) -> str:
        return f'Relatório Market Intel {self.date}'


class MarketIntelCursor(TimestampedModel):
    """Cursor operacional por fonte; mantém processamento incremental idempotente."""

    source = models.CharField(max_length=64, unique=True)
    last_message_sent_at = models.DateTimeField(null=True, blank=True)
    last_message_id = models.PositiveIntegerField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    processed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'cursor de inteligência de mercado'
        verbose_name_plural = 'cursores de inteligência de mercado'


class ObservedOpportunity(TimestampedModel):
    class Status(models.TextChoices):
        OBSERVED = 'observed', 'Observada'
        NORMALIZED = 'normalized', 'Normalizada'
        MATCHED_CATALOG = 'matched_catalog', 'Catalogada'
        CANDIDATE = 'candidate', 'Candidata'
        ENRICHMENT_PENDING = 'enrichment_pending', 'Aguardando enriquecimento'
        ENRICHED = 'enriched', 'Enriquecida'
        SENT_TO_CURATION = 'sent_to_curation', 'Enviada à curadoria'
        EXPIRED = 'expired', 'Expirada'
        REJECTED_FOR_FRESHNESS = 'rejected_for_freshness', 'Rejeitada por frescor'

    fingerprint = models.CharField(max_length=64, unique=True)
    marketplace = models.CharField(max_length=64, blank=True)
    category = models.CharField(max_length=120, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    coupon = models.CharField(max_length=80, blank=True)
    price_band = models.CharField(max_length=32, blank=True)
    latest_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_discount_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    first_observed_at = models.DateTimeField()
    last_observed_at = models.DateTimeField()
    occurrence_count = models.PositiveIntegerField(default=0)
    source_group_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OBSERVED)
    parser_version = models.CharField(max_length=16, default='2')
    last_message_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-last_observed_at', '-occurrence_count']
        indexes = [
            models.Index(fields=['status', 'last_observed_at']),
            models.Index(fields=['marketplace', 'category']),
        ]


class LearningEvent(TimestampedModel):
    event_type = models.CharField(max_length=64)
    key = models.CharField(max_length=180)
    observed_at = models.DateTimeField()
    payload = models.JSONField(default=dict, blank=True)
    policy_version = models.CharField(max_length=16, default='1')

    class Meta:
        indexes = [models.Index(fields=['event_type', 'observed_at'])]


class MarketLearningSnapshot(TimestampedModel):
    class State(models.TextChoices):
        SHADOW = 'shadow', 'Shadow'
        CANDIDATE = 'candidate', 'Candidata'
        APPROVED = 'approved', 'Aprovada'
        ACTIVE = 'active', 'Ativa'
        ROLLED_BACK = 'rolled_back', 'Revertida'

    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    schema_version = models.CharField(max_length=16, default='1')
    policy_version = models.CharField(max_length=16, default='1')
    state = models.CharField(max_length=16, choices=State.choices, default=State.SHADOW)
    sample_size = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-period_end', '-id']
        indexes = [models.Index(fields=['state', 'period_end'])]
