from django import forms


class AmazonUploadForm(forms.Form):
    file = forms.FileField(
        label='Arquivo do relatório (TSV ou CSV)',
        help_text=(
            'Exporte o relatório por ASIN no painel Amazon Associates '
            '(formato Tab-delimited UTF-8) e selecione o arquivo aqui.'
        ),
    )
    period_start = forms.DateField(
        label='Início do período',
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Período coberto pelo relatório (Amazon não inclui no arquivo).',
    )
    period_end = forms.DateField(
        label='Fim do período',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('period_start')
        end = cleaned.get('period_end')
        if start and end and start > end:
            raise forms.ValidationError('Início do período não pode ser maior que o fim.')
        return cleaned


class MercadoLivreUploadForm(forms.Form):
    pasted_json = forms.CharField(
        label='JSON copiado do DevTools',
        widget=forms.Textarea(attrs={'rows': 12, 'style': 'font-family: monospace;'}),
        required=False,
        help_text=(
            'No painel ML Afiliados, abra DevTools → Network, copie a response '
            'do XHR e cole aqui. O período é lido do campo filter_time_range.'
        ),
    )
    file = forms.FileField(
        label='OU envie um arquivo .json',
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('pasted_json') and not cleaned.get('file'):
            raise forms.ValidationError(
                'Informe o JSON colado ou anexe um arquivo .json.'
            )
        return cleaned
