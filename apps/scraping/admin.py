from django.contrib import admin

from apps.scraping.models import ScrapingRun


@admin.register(ScrapingRun)
class ScrapingRunAdmin(admin.ModelAdmin):
    list_display = (
        'marketplace',
        'status',
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
