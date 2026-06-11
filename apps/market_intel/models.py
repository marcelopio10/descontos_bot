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
    parsed_marketplace = models.CharField(max_length=64, blank=True)
    parsed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parsed_original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parsed_discount_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    parsed_coupon = models.CharField(max_length=80, blank=True)
    editorial_labels = models.JSONField(default=list, blank=True)
    scraper_hints = models.JSONField(default=list, blank=True)
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
    site_payload_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']

    def __str__(self) -> str:
        return f'Relatório Market Intel {self.date}'
