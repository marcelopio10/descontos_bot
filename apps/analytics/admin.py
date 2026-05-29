from django.contrib import admin

from apps.analytics.models import ClickEvent


@admin.register(ClickEvent)
class ClickEventAdmin(admin.ModelAdmin):
    list_display = (
        'offer',
        'social_channel',
        'utm_source',
        'utm_campaign',
        'clicked_at',
        'created_at',
    )
    list_filter = (
        'social_channel',
        'utm_source',
        ('clicked_at', admin.DateFieldListFilter),
        'offer__marketplace',
    )
    search_fields = (
        'utm_source',
        'utm_medium',
        'utm_campaign',
        'utm_content',
        'offer__title',
        'offer__slug',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'offer',
    )
    date_hierarchy = 'clicked_at'
