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


class ObservedOfferLink(models.Model):
    """Resolução de um link de oferta divulgado por um grupo concorrente.

    O observer já captura ~4.4 mil mensagens de Mercado Livre por semana, mas o
    link vem encurtado (`meli.la/...`) e aponta para a vitrine de afiliado de
    quem publicou — não para o anúncio. Este modelo guarda o resultado de abrir
    esse link uma única vez: qual anúncio é, com que preço e com que cupom.

    Existe separado da mensagem por três motivos: uma mensagem pode conter mais
    de um link; a resolução falha por motivos próprios (link morto, vitrine sem
    card, bloqueio) que precisam ser auditáveis; e o mesmo anúncio chega por
    vários grupos, então a deduplicação real acontece por `external_item_id`,
    não por mensagem.

    O que **não** entra aqui: nada que identifique grupo ou remetente. Essa
    associação já vive em `ObservedWhatsAppMessage`; o payload que segue para a
    oferta é sanitizado em `build_sanitized_raw_payload`.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        RESOLVED = 'resolved', 'Resolvido'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Ignorado'

    message = models.ForeignKey(
        ObservedWhatsAppMessage,
        on_delete=models.CASCADE,
        related_name='offer_links',
    )
    source_url = models.CharField(max_length=1500)
    marketplace_code = models.CharField(max_length=40)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=300, blank=True)

    resolved_url = models.CharField(max_length=1500, blank=True)
    external_item_id = models.CharField(max_length=64, blank=True)
    title = models.CharField(max_length=500, blank=True)
    image_url = models.CharField(max_length=1500, blank=True)
    seller = models.CharField(max_length=200, blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    affiliate_url = models.CharField(max_length=1500, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['message', 'source_url'],
                name='unique_observed_offer_link',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'resolved_at']),
            models.Index(fields=['external_item_id']),
        ]

    def __str__(self) -> str:
        return f'{self.marketplace_code}:{self.external_item_id or self.source_url}'


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
