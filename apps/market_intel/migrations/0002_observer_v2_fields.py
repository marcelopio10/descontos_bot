from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('market_intel', '0001_initial'),
    ]

    operations = [
        # P0-1: Sinais de engajamento (null para WhatsApp, preenchido no futuro para Telegram)
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='reacoes',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='visualizacoes',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='encaminhamentos',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='comentarios',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='repostado',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='qtd_repostagens',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='fixado',
            field=models.BooleanField(null=True, blank=True),
        ),

        # P0-2: Mecânica de preço
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='parcelamento',
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='parcelado_sem_juros',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='pix',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='pix_desconto_pct',
            field=models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='cashback',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='cashback_valor',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='menor_preco',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='cupom_tipo',
            field=models.CharField(max_length=20, blank=True),
        ),

        # P0-3: Padrões de copy e formato
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='emoji_densidade',
            field=models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='emojis_top',
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='tem_headline',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='tem_de_por',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='tem_cta',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='cta_termos',
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='tipo_midia',
            field=models.CharField(max_length=20, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='tamanho_mensagem',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='usa_caixa_alta',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='usa_negrito',
            field=models.BooleanField(null=True, blank=True),
        ),

        # P1-5: Marketplace mais rico
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='marketplace_dominio_desconhecido',
            field=models.CharField(max_length=500, blank=True),
        ),
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='programa_entrega',
            field=models.CharField(max_length=20, blank=True),
        ),

        # P1-6: Marca dentro da categoria
        migrations.AddField(
            model_name='observedwhatsappmessage',
            name='marca',
            field=models.CharField(max_length=80, blank=True),
        ),

        # P1-4: Cadência (sem campos novos — derivado de sent_at)

        # Report version
        migrations.AddField(
            model_name='marketinteldailyreport',
            name='payload_version',
            field=models.CharField(max_length=8, default='2.0'),
        ),
    ]