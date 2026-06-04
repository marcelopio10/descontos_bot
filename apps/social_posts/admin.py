import traceback

from django.contrib import admin, messages
from django.utils import timezone

from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    publish_story,
    record_failure,
)
from apps.social_posts.services.instagram_handoff_telegram import (
    HandoffDisabled,
    HandoffError,
    deliver_post_to_handoff,
    mark_post_as_posted,
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


@admin.action(description='Marcar como postado manualmente (com edição do botão Telegram)')
def mark_as_posted_manual(modeladmin, request, queryset):
    success = 0
    for post in queryset:
        try:
            mark_post_as_posted(post, actor='admin_manual')
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Post #{post.id}: {exc}')
        else:
            success += 1
    modeladmin.message_user(
        request,
        f'{success} post(ns) marcado(s) como postado(s) manualmente.',
    )


@admin.action(description='Re-enviar pacote Telegram (handoff)')
def resend_handoff(modeladmin, request, queryset):
    sent = 0
    failed = 0
    for post in queryset:
        if post.format != InstagramPost.Format.STORY:
            messages.warning(
                request,
                f'Post #{post.id} ignorado — handoff só suporta story.',
            )
            continue
        # Limpa o id antigo pra forçar reentrega.
        post.telegram_handoff_message_id = ''
        post.save(update_fields=['telegram_handoff_message_id', 'updated_at'])
        try:
            deliver_post_to_handoff(post)
        except HandoffDisabled as exc:
            failed += 1
            messages.error(request, f'Post #{post.id}: handoff desativado — {exc}')
        except HandoffError as exc:
            failed += 1
            messages.error(request, f'Post #{post.id}: {exc}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            messages.error(request, f'Post #{post.id}: erro inesperado — {exc}')
        else:
            sent += 1
    modeladmin.message_user(
        request,
        f'Handoff: {sent} reenviado(s), {failed} falha(s).',
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


@admin.action(description='Publicar via Composio (modo manual/fallback)')
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
        'telegram_handoff_message_id',
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
        'telegram_handoff_message_id',
    )
    readonly_fields = (
        'instagram_media_id',
        'telegram_handoff_message_id',
        'posted_at',
        'published_error',
        'created_at',
        'updated_at',
    )
    autocomplete_fields = (
        'primary_offer',
        'related_offers',
    )
    actions = (
        resend_handoff,
        mark_as_posted_manual,
        approve_and_publish,
        mark_as_posted,
        mark_as_rejected,
    )
