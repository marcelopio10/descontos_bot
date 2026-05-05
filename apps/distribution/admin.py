from django.contrib import admin

from apps.distribution.models import Delivery, SocialChannel


@admin.register(SocialChannel)
class SocialChannelAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'channel_type',
        'target',
        'is_enabled',
        'updated_at',
    )
    list_filter = (
        'channel_type',
        'is_enabled',
    )
    search_fields = (
        'name',
        'code',
        'target',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        'offer',
        'social_channel',
        'delivery_status',
        'sent_at',
        'updated_at',
    )
    list_filter = (
        'delivery_status',
        'social_channel',
    )
    search_fields = (
        'offer__title',
        'social_channel__name',
        'external_message_id',
        'error_message',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'offer',
        'social_channel',
    )
