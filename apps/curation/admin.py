from django.contrib import admin

from apps.curation.models import (
    CuratedBatch,
    CuratedBatchItem,
    CurationBlacklistTerm,
    CurationDecision,
    CurationRun,
)


class CurationDecisionInline(admin.TabularInline):
    model = CurationDecision
    extra = 0
    fields = ('offer', 'marketplace_code', 'baseline_score', 'ai_score', 'ai_classification', 'is_selected_for_batch')
    readonly_fields = fields
    can_delete = False
    show_change_link = True


class CuratedBatchItemInline(admin.TabularInline):
    model = CuratedBatchItem
    extra = 0
    fields = ('position', 'offer', 'send_status', 'final_title', 'delivery')
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(CurationRun)
class CurationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'channel', 'status', 'mode', 'candidate_count', 'selected_count', 'schema_version', 'created_at')
    list_filter = ('status', 'mode', 'channel')
    search_fields = ('profile_name', 'model_name', 'error_message')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (CurationDecisionInline,)


@admin.register(CurationDecision)
class CurationDecisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'offer', 'marketplace_code', 'baseline_score', 'ai_score', 'ai_classification', 'is_selected_for_batch')
    list_filter = ('ai_classification', 'is_selected_for_batch', 'marketplace_code')
    search_fields = ('offer__title', 'title_original', 'title_rewritten', 'decision_reason')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CuratedBatch)
class CuratedBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'channel', 'status', 'batch_size', 'expires_at', 'consumed_at', 'created_at')
    list_filter = ('status', 'channel')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (CuratedBatchItemInline,)


@admin.register(CuratedBatchItem)
class CuratedBatchItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'position', 'offer', 'send_status', 'delivery')
    list_filter = ('send_status',)
    search_fields = ('offer__title', 'final_title', 'final_caption_whatsapp', 'final_caption_telegram')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CurationBlacklistTerm)
class CurationBlacklistTermAdmin(admin.ModelAdmin):
    list_display = ('id', 'term', 'source', 'status', 'offer', 'run', 'added_to_setting_at', 'rolled_back_at')
    list_filter = ('source', 'status')
    search_fields = ('term', 'normalized_term', 'rollback_reason')
    readonly_fields = ('created_at', 'updated_at')
