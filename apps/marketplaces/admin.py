from django.contrib import admin

from apps.marketplaces.models import Marketplace


@admin.register(Marketplace)
class MarketplaceAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'is_active',
        'affiliate_enabled',
        'updated_at',
    )
    list_filter = (
        'is_active',
        'affiliate_enabled',
    )
    search_fields = (
        'name',
        'code',
        'base_url',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
