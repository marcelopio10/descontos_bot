from django.contrib import admin

from apps.social_posts.models import InstagramPost


@admin.register(InstagramPost)
class InstagramPostAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'format',
        'status',
        'primary_offer',
        'posted_at',
        'created_at',
    )
    list_filter = (
        'format',
        'status',
    )
    search_fields = (
        'primary_offer__title',
        'caption',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'primary_offer',
        'related_offers',
    )
