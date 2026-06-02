from django import forms


class AmazonUploadForm(forms.Form):
    file = forms.FileField(
        label='Arquivo do relatório (TSV ou CSV)',
        help_text=(
            'Exporte o Earnings Report no painel Amazon Associates (formato '
            'Tab-delimited UTF-8) e selecione o arquivo aqui.'
        ),
    )


class MercadoLivreUploadForm(forms.Form):
    pasted_json = forms.CharField(
        label='JSON copiado do DevTools',
        widget=forms.Textarea(attrs={'rows': 12, 'style': 'font-family: monospace;'}),
        required=False,
        help_text=(
            'No painel ML Afiliados, abra DevTools → Network, identifique a '
            'response do relatório e cole o JSON aqui. SubID esperado: '
            'dbot_<canal>_<offer_id>.'
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
