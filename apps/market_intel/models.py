from django.db import models


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
