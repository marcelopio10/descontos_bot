from django.db import models
from apps._base.models import TimestampedModel
from apps.distribution.models import SocialChannel


class CouponRun(TimestampedModel):
    run_key = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=20, default='running')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    sources_json = models.JSONField(default=list, blank=True)
    observer_pattern_json = models.JSONField(default=dict, blank=True)
    candidates_found = models.PositiveIntegerField(default=0)
    selected_count = models.PositiveIntegerField(default=0)
    errors_json = models.JSONField(default=list, blank=True)


class CouponCandidate(TimestampedModel):
    run = models.ForeignKey(CouponRun, on_delete=models.CASCADE, related_name='candidates')
    candidate_hash = models.CharField(max_length=64)
    marketplace = models.CharField(max_length=40)
    activation_code = models.CharField(max_length=160, blank=True)
    activation_method = models.CharField(max_length=160, blank=True)
    benefit = models.CharField(max_length=500, blank=True)
    minimum_purchase = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    maximum_discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    restrictions = models.JSONField(default=list, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(max_length=1500)
    campaign_url = models.URLField(max_length=1500, blank=True)
    destination_url = models.URLField(max_length=1500)
    affiliate_url = models.URLField(max_length=1500, blank=True)
    evidence = models.TextField(blank=True)
    source_confidence = models.CharField(max_length=30, default='low')
    validation_status = models.CharField(max_length=30, default='pending')
    rejection_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'candidate_hash'], name='unique_coupon_run_hash')]
        indexes = [models.Index(fields=['marketplace', 'candidate_hash'])]


class CouponDecision(TimestampedModel):
    candidate = models.OneToOneField(CouponCandidate, on_delete=models.CASCADE, related_name='decision')
    classification = models.CharField(max_length=20)
    selected = models.BooleanField(default=False)
    relevance_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    benefit_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reliability_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    frustration_risk_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    reason = models.TextField(blank=True)
    whatsapp_post = models.TextField(blank=True)
    telegram_post = models.TextField(blank=True)
    editorial_structure_json = models.JSONField(default=dict, blank=True)


class CouponDelivery(TimestampedModel):
    candidate = models.ForeignKey(CouponCandidate, on_delete=models.PROTECT, related_name='deliveries')
    channel = models.ForeignKey(SocialChannel, on_delete=models.PROTECT, related_name='coupon_deliveries')
    message = models.TextField()
    status = models.CharField(max_length=20, default='pending')
    external_message_id = models.CharField(max_length=160, blank=True)
    error_message = models.TextField(blank=True)
    published_url = models.URLField(max_length=1500, blank=True)
    affiliate_used = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['candidate', 'channel'], name='unique_coupon_delivery_channel')]
