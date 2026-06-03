import traceback

from django.contrib import admin, messages
from django.utils import timezone

from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    publish_story,
    record_failure,
)


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


@admin.action(description='Aprovar e publicar agora (story via Composio)')
def approve_and_publish(modeladmin, request, queryset):
    success = 0
    skipped = 0
    failed = 0
    for post in queryset:
        if post.format != InstagramPost.Format.STORY:
            skipped += 1
            messages.warning(
                request,
                f'Post #{post.id} ignorado — apenas story suportado por enquanto.',
            )
            continue
        if post.status == InstagramPost.Status.POSTED:
            skipped += 1
            messages.info(request, f'Post #{post.id} já está publicado.')
            continue

        try:
            result = publish_story(post)
        except ComposioPublishError as exc:
            failed += 1
            error = f'[{exc.stage}] {exc}'
            record_failure(post, error)
            messages.error(request, f'Post #{post.id}: {error}')
        except Exception as exc:
            failed += 1
            error = f'{exc}\n{traceback.format_exc()}'
            record_failure(post, error)
            messages.error(request, f'Post #{post.id}: erro inesperado — {exc}')
        else:
            success += 1
            messages.success(
                request,
                f'Post #{post.id} publicado — media {result.media_id}.',
            )

    modeladmin.message_user(
        request,
        f'Resumo: {success} publicado(s), {failed} falha(s), {skipped} ignorado(s).',
    )


@admin.register(InstagramPost)
class InstagramPostAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'format',
        'status',
        'primary_offer',
        'instagram_media_id',
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
        'instagram_media_id',
    )
    readonly_fields = (
        'instagram_media_id',
        'posted_at',
        'published_error',
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'primary_offer',
        'related_offers',
    )
    actions = (approve_and_publish, mark_as_posted, mark_as_rejected,)
