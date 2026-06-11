from django.contrib import admin

from apps.market_intel.models import (
    MarketIntelDailyReport,
    ObservedWhatsAppGroup,
    ObservedWhatsAppMessage,
)


@admin.register(ObservedWhatsAppGroup)
class ObservedWhatsAppGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'jid', 'is_enabled', 'updated_at')
    search_fields = ('name', 'jid')
    list_filter = ('is_enabled',)


@admin.register(ObservedWhatsAppMessage)
class ObservedWhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ('group', 'external_message_id', 'parsed_marketplace', 'parsed_price', 'has_image', 'sent_at')
    search_fields = ('group__name', 'external_message_id', 'text')
    list_filter = ('parsed_marketplace', 'has_image', 'raw_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(MarketIntelDailyReport)
class MarketIntelDailyReportAdmin(admin.ModelAdmin):
    list_display = ('date', 'groups_analyzed', 'messages_analyzed', 'site_payload_path', 'created_at')
    search_fields = ('site_payload_path',)
    readonly_fields = ('created_at', 'updated_at')
