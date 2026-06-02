import json

from django.contrib import admin
from django.utils.html import format_html

from apps.curation.services.blacklist import is_blacklisted
from apps.curation.services.quality_score import quality_score_breakdown
from apps.offers.models import Offer


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'marketplace',
        'current_price',
        'original_price',
        'discount_pct',
        'quality_score_column',
        'is_active',
        'last_seen_at',
    )
    list_filter = (
        'marketplace',
        'is_active',
    )
    search_fields = (
        'title',
        'normalized_title',
        'external_id',
        'offer_hash',
        'product_url',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'first_seen_at',
        'last_seen_at',
        'quality_score_breakdown_display',
        'blacklist_status_display',
    )
    autocomplete_fields = (
        'marketplace',
    )

    @admin.display(description='score', ordering=None)
    def quality_score_column(self, obj: Offer) -> str:
        score = quality_score_breakdown(obj).score
        color = '#2e8b57' if score >= 60 else ('#d4a017' if score >= 30 else '#b22222')
        return format_html(
            '<strong style="color: {};">{}</strong>',
            color,
            f'{score:.1f}',
        )

    @admin.display(description='score detalhado')
    def quality_score_breakdown_display(self, obj: Offer) -> str:
        breakdown = quality_score_breakdown(obj).as_dict()
        return format_html(
            '<pre style="margin: 0;">{}</pre>',
            json.dumps(breakdown, indent=2, ensure_ascii=False),
        )

    @admin.display(description='blacklist')
    def blacklist_status_display(self, obj: Offer) -> str:
        if is_blacklisted(obj):
            return format_html(
                '<strong style="color: #b22222;">{}</strong>',
                'na blacklist (termo proibido no título)',
            )
        return 'OK'
