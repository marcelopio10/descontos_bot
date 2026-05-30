from django.contrib import admin
from django.utils import timezone

from apps.social_posts.models import InstagramPost


@admin.action(description='Marcar como postado')
def mark_as_posted(modeladmin, request, queryset):
    updated = queryset.exclude(status=InstagramPost.Status.POSTED).update(
        status=InstagramPost.Status.POSTED,
        posted_at=timezone.now(),
    )
    if updated:
        modeladmin.message_user(
            request,
            f'{updated} post(ns) marcado(s) como postado(s).',
        )
    else:
        modeladmin.message_user(
            request,
            'Nenhum post alterado — todos os selecionados já estavam como postado.',
        )


@admin.action(description='Marcar como rejeitado')
def mark_as_rejected(modeladmin, request, queryset):
    updated = queryset.exclude(status=InstagramPost.Status.REJECTED).update(
        status=InstagramPost.Status.REJECTED,
        posted_at=None,
    )
    if updated:
        modeladmin.message_user(
            request,
            f'{updated} post(ns) marcado(s) como rejeitado(s).',
        )
    else:
        modeladmin.message_user(
            request,
            'Nenhum post alterado — todos os selecionados já estavam como rejeitado.',
        )


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
    actions = (mark_as_posted, mark_as_rejected,)
