from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.analytics.forms import AmazonUploadForm, MercadoLivreUploadForm
from apps.analytics.models import (
    AffiliateConversion,
    AffiliateImportBatch,
    ClickEvent,
)
from apps.analytics.services.affiliate_parsers.amazon import parse_amazon_tsv
from apps.analytics.services.affiliate_parsers.mercadolivre import (
    parse_mercadolivre_payload,
)
from apps.analytics.services.affiliate_summary import publish_affiliate_summary


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


@admin.register(AffiliateImportBatch)
class AffiliateImportBatchAdmin(admin.ModelAdmin):
    change_list_template = 'admin/analytics/affiliateimportbatch/change_list.html'

    list_display = (
        'id',
        'source',
        'period_start',
        'period_end',
        'rows_imported',
        'rows_skipped',
        'raw_filename',
        'created_at',
    )
    list_filter = (
        'source',
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'raw_filename',
        'payload_sha256',
        'notes',
    )
    readonly_fields = (
        'source',
        'period_start',
        'period_end',
        'raw_filename',
        'payload_sha256',
        'rows_imported',
        'rows_skipped',
        'notes',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'import-amazon/',
                self.admin_site.admin_view(self.import_amazon_view),
                name='analytics_affiliateimportbatch_import_amazon',
            ),
            path(
                'import-mercadolivre/',
                self.admin_site.admin_view(self.import_mercadolivre_view),
                name='analytics_affiliateimportbatch_import_mercadolivre',
            ),
        ]
        return custom + urls

    def import_amazon_view(self, request):
        if request.method == 'POST':
            form = AmazonUploadForm(request.POST, request.FILES)
            if form.is_valid():
                uploaded = form.cleaned_data['file']
                try:
                    result = parse_amazon_tsv(
                        uploaded.read(),
                        filename=uploaded.name,
                        commit=True,
                    )
                except ValueError as exc:
                    messages.error(request, f'Falha ao processar arquivo: {exc}')
                else:
                    publish_affiliate_summary()
                    self._report_result(request, result, source_label='Amazon')
                    return redirect(reverse(
                        'admin:analytics_affiliateimportbatch_changelist'
                    ))
        else:
            form = AmazonUploadForm()

        return render(
            request,
            'admin/analytics/affiliateimportbatch/import_form.html',
            self._template_context(request, form, title='Importar Amazon Associates'),
        )

    def import_mercadolivre_view(self, request):
        if request.method == 'POST':
            form = MercadoLivreUploadForm(request.POST, request.FILES)
            if form.is_valid():
                uploaded = form.cleaned_data.get('file')
                pasted = form.cleaned_data.get('pasted_json') or ''
                if uploaded:
                    payload = uploaded.read()
                    filename = uploaded.name
                else:
                    payload = pasted.encode('utf-8')
                    filename = 'paste.json'
                try:
                    result = parse_mercadolivre_payload(
                        payload,
                        filename=filename,
                        commit=True,
                    )
                except ValueError as exc:
                    messages.error(request, f'Falha ao processar payload: {exc}')
                else:
                    publish_affiliate_summary()
                    self._report_result(request, result, source_label='Mercado Livre')
                    return redirect(reverse(
                        'admin:analytics_affiliateimportbatch_changelist'
                    ))
        else:
            form = MercadoLivreUploadForm()

        return render(
            request,
            'admin/analytics/affiliateimportbatch/import_form.html',
            self._template_context(
                request, form, title='Importar Mercado Livre Afiliados'
            ),
        )

    def _template_context(self, request, form, title):
        return {
            **self.admin_site.each_context(request),
            'form': form,
            'title': title,
            'opts': self.model._meta,
        }

    def _report_result(self, request, result, source_label: str):
        level = messages.SUCCESS if result.imported else messages.WARNING
        messages.add_message(
            request,
            level,
            (
                f'{source_label}: importadas {result.imported} linhas, '
                f'ignoradas {result.skipped}. '
                f'Período {result.period_start}..{result.period_end}.'
            ),
        )
        for warning in result.warnings:
            messages.warning(request, warning)


@admin.register(AffiliateConversion)
class AffiliateConversionAdmin(admin.ModelAdmin):
    list_display = (
        'report_date',
        'source',
        'offer',
        'social_channel',
        'conversions',
        'clicks',
        'commission_brl',
        'revenue_brl',
        'subid',
        'batch_link',
    )
    list_filter = (
        'source',
        'social_channel',
        ('report_date', admin.DateFieldListFilter),
        'offer__marketplace',
    )
    search_fields = (
        'subid',
        'offer__title',
        'offer__slug',
        'offer__asin',
        'offer__external_id',
    )
    readonly_fields = (
        'offer',
        'social_channel',
        'source',
        'subid',
        'report_date',
        'clicks',
        'conversions',
        'revenue_brl',
        'commission_brl',
        'batch',
        'created_at',
        'updated_at',
    )
    autocomplete_fields = ()
    date_hierarchy = 'report_date'

    def has_add_permission(self, request):
        return False

    @admin.display(description='lote')
    def batch_link(self, obj):
        if not obj.batch_id:
            return '—'
        url = reverse(
            'admin:analytics_affiliateimportbatch_change',
            args=[obj.batch_id],
        )
        return format_html('<a href="{}">#{}</a>', url, obj.batch_id)
