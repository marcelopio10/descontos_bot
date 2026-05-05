from django.contrib import admin

from apps.offers.models import Offer


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'marketplace',
        'current_price',
        'original_price',
        'discount_pct',
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
    )
    autocomplete_fields = (
        'marketplace',
    )
