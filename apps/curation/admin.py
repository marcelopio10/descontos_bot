from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.curation.models import (
    CuratedBatch,
    CuratedBatchItem,
    CurationBlacklistTerm,
    CurationDecision,
    CurationRun,
)


# ===========================================================================
# Helpers / Actions compartilhadas
# ===========================================================================

def _mudar_status(modeladmin, request, queryset, novo_status, descricao):
    """Atualiza o status dos registros selecionados em lote."""
    updated = queryset.update(status=novo_status)
    modeladmin.message_user(request, f'{updated} registro(s) alterado(s) para "{descricao}".')


# ===========================================================================
# Inlines
# ===========================================================================

class CurationDecisionInline(admin.TabularInline):
    """Inline das decisões de curadoria dentro da execução."""
    model = CurationDecision
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        'offer', 'marketplace_code', 'baseline_score', 'ai_score',
        'ai_classification', 'is_selected_for_batch',
    )
    readonly_fields = fields
    autocomplete_fields = ('offer',)


class CuratedBatchItemInline(admin.TabularInline):
    """Inline dos itens dentro de um lote curado."""
    model = CuratedBatchItem
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ('position', 'offer', 'send_status', 'final_title')
    readonly_fields = ('position', 'send_status', 'final_title')
    autocomplete_fields = ('offer',)


# ===========================================================================
# CurationRun
# ===========================================================================

@admin.register(CurationRun)
class CurationRunAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'channel', 'status', 'mode', 'candidate_count',
        'selected_count', 'schema_version', 'created_at',
    )
    list_filter = ('status', 'mode', 'channel')
    search_fields = ('profile_name', 'model_name', 'error_message')
    date_hierarchy = 'created_at'
    list_select_related = ('channel',)
    inlines = (CurationDecisionInline,)

    fieldsets = (
        (_('Identificação'), {
            'fields': ('channel', 'status', 'mode', 'profile_name'),
        }),
        (_('Modelo de IA'), {
            'fields': ('model_provider', 'model_name', 'schema_version'),
        }),
        (_('Resultados'), {
            'fields': ('candidate_count', 'selected_count', 'error_message'),
        }),
        (_('Distribuição e Contexto'), {
            'classes': ('collapse',),
            'fields': (
                'target_distribution_json', 'actual_distribution_json',
                'observer_context_json', 'baseline_summary_json',
            ),
        }),
        (_('Arquivos'), {
            'classes': ('collapse',),
            'fields': ('input_json_path', 'output_json_path', 'public_json_path'),
        }),
        (_('Timeline'), {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'candidate_count', 'selected_count', 'schema_version',
    )

    actions = ('marcar_concluida', 'marcar_cancelada', 'marcar_falha')

    @admin.action(description='Marcar execuções selecionadas como concluídas')
    def marcar_concluida(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CurationRun.Status.COMPLETED, 'concluída')

    @admin.action(description='Cancelar execuções selecionadas')
    def marcar_cancelada(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CurationRun.Status.CANCELLED, 'cancelada')

    @admin.action(description='Marcar execuções selecionadas como falha')
    def marcar_falha(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CurationRun.Status.FAILED, 'falha')


# ===========================================================================
# CurationDecision
# ===========================================================================

@admin.register(CurationDecision)
class CurationDecisionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'run', 'offer', 'marketplace_code', 'baseline_score',
        'ai_score', 'ai_classification', 'is_selected_for_batch',
    )
    list_filter = ('ai_classification', 'is_selected_for_batch', 'marketplace_code')
    search_fields = ('offer__title', 'title_original', 'title_rewritten', 'decision_reason')
    date_hierarchy = 'created_at'
    list_select_related = ('run', 'offer')
    autocomplete_fields = ('offer',)
    raw_id_fields = ('run',)

    fieldsets = (
        (_('Identificação'), {
            'fields': ('run', 'offer', 'marketplace_code', 'is_selected_for_batch'),
        }),
        (_('Score — Baseline'), {
            'fields': ('baseline_score', 'baseline_classification', 'baseline_decision'),
        }),
        (_('Score — IA'), {
            'fields': (
                'ai_score', 'ai_classification',
                'conversion_score', 'relevance_score',
                'discount_quality_score', 'audience_fit_score',
                'image_score',
            ),
        }),
        (_('Conteúdo'), {
            'fields': (
                'title_original', 'title_rewritten',
                'caption_rewritten', 'decision_reason',
            ),
        }),
        (_('Análises (somente leitura)'), {
            'classes': ('collapse',),
            'fields': (
                'risk_flags_json', 'observer_signals_json',
                'image_analysis_json', 'blacklist_terms_json',
            ),
        }),
        (_('Raw IA'), {
            'classes': ('collapse',),
            'fields': ('raw_ai_json',),
        }),
        (_('Timeline'), {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'risk_flags_json', 'observer_signals_json',
        'image_analysis_json', 'blacklist_terms_json', 'raw_ai_json',
    )


# ===========================================================================
# CuratedBatch
# ===========================================================================

@admin.register(CuratedBatch)
class CuratedBatchAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'channel', 'run', 'status', 'batch_size',
        'expires_at', 'consumed_at', 'created_at',
    )
    list_filter = ('status', 'channel')
    date_hierarchy = 'created_at'
    list_select_related = ('channel', 'run')
    inlines = (CuratedBatchItemInline,)

    fieldsets = (
        (_('Identificação'), {
            'fields': ('run', 'channel', 'status', 'batch_size'),
        }),
        (_('Distribuição'), {
            'classes': ('collapse',),
            'fields': ('target_distribution_json', 'actual_distribution_json'),
        }),
        (_('Timeline'), {
            'fields': ('expires_at', 'consumed_at', 'created_at', 'updated_at'),
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'target_distribution_json', 'actual_distribution_json',
    )

    actions = ('marcar_pronto', 'marcar_enviado', 'marcar_expirado')

    @admin.action(description='Marcar lotes selecionados como prontos')
    def marcar_pronto(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CuratedBatch.Status.READY, 'pronto')

    @admin.action(description='Marcar lotes selecionados como enviados')
    def marcar_enviado(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CuratedBatch.Status.SENT, 'enviado')

    @admin.action(description='Marcar lotes selecionados como expirados')
    def marcar_expirado(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CuratedBatch.Status.EXPIRED, 'expirado')


# ===========================================================================
# CuratedBatchItem
# ===========================================================================

@admin.register(CuratedBatchItem)
class CuratedBatchItemAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'batch', 'position', 'offer',
        'send_status', 'delivery',
    )
    list_filter = ('send_status',)
    search_fields = (
        'offer__title', 'final_title',
        'final_caption_whatsapp', 'final_caption_telegram',
    )
    date_hierarchy = 'created_at'
    list_select_related = ('batch', 'offer', 'decision', 'delivery')
    autocomplete_fields = ('offer',)
    raw_id_fields = ('batch', 'decision', 'delivery')

    fieldsets = (
        (_('Identificação'), {
            'fields': ('batch', 'decision', 'offer', 'position', 'send_status'),
        }),
        (_('Conteúdo'), {
            'fields': (
                'final_title', 'final_caption_whatsapp',
                'final_caption_telegram',
            ),
        }),
        (_('Imagem'), {
            'classes': ('collapse',),
            'fields': (
                'final_image_url', 'local_image_path',
                'image_width', 'image_height', 'image_mime_type',
            ),
        }),
        (_('Entrega'), {
            'fields': ('delivery',),
        }),
        (_('Timeline'), {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'local_image_path', 'image_width', 'image_height', 'image_mime_type',
    )


# ===========================================================================
# CurationBlacklistTerm
# ===========================================================================

@admin.register(CurationBlacklistTerm)
class CurationBlacklistTermAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'term', 'normalized_term', 'source', 'status',
        'offer', 'run', 'added_to_setting_at', 'rolled_back_at',
    )
    list_filter = ('source', 'status')
    search_fields = ('term', 'normalized_term', 'rollback_reason')
    date_hierarchy = 'created_at'
    list_select_related = ('offer', 'decision', 'run')
    autocomplete_fields = ('offer',)
    raw_id_fields = ('decision', 'run')

    fieldsets = (
        (_('Termo'), {
            'fields': ('term', 'normalized_term', 'source', 'status'),
        }),
        (_('Associação'), {
            'fields': ('offer', 'decision', 'run'),
        }),
        (_('Timeline de Rollback'), {
            'fields': (
                'added_to_setting_at', 'rolled_back_at',
                'rollback_reason', 'created_at', 'updated_at',
            ),
        }),
    )

    readonly_fields = (
        'created_at', 'updated_at',
        'normalized_term', 'added_to_setting_at',
        'rolled_back_at', 'rollback_reason',
    )

    actions = ('reativar_termos', 'reverter_termos')

    @admin.action(description='Reativar termos selecionados')
    def reativar_termos(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CurationBlacklistTerm.Status.ACTIVE, 'ativo')

    @admin.action(description='Reverter (desativar) termos selecionados')
    def reverter_termos(self, request, queryset):
        _mudar_status(self, request, queryset,
                       CurationBlacklistTerm.Status.ROLLED_BACK, 'revertido')
