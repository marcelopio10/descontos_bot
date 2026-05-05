from django.contrib import admin

from apps.panel.models import Setting


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = (
        'key',
        'value',
        'updated_at',
    )
    search_fields = (
        'key',
        'value',
        'description',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
