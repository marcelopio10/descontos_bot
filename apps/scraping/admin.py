from django.contrib import admin

from apps.scraping.models import ScrapingItemResult, ScrapingRun


@admin.register(ScrapingRun)
class ScrapingRunAdmin(admin.ModelAdmin):
    list_display = (
        'marketplace',
        'status',
        'provider',
        'total_collected',
        'total_valid',
        'started_at',
        'finished_at',
    )
    list_filter = (
        'status',
        'marketplace',
    )
    search_fields = (
        'marketplace__name',
        'marketplace__code',
        'error_message',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'marketplace',
    )


@admin.register(ScrapingItemResult)
class ScrapingItemResultAdmin(admin.ModelAdmin):
    list_display = (
        'run',
        'sequence',
        'external_id',
        'status',
        'reason_code',
        'processed_at',
    )
    list_filter = ('status', 'reason_code')
    search_fields = ('external_id', 'source', 'reason_code', 'error_message')
    readonly_fields = ('created_at', 'updated_at', 'processed_at')
    autocomplete_fields = ('run', 'offer')
