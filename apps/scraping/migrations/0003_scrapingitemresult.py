import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offers', '0010_mercadolivre_metadata'),
        ('scraping', '0002_scrapingrun_provider'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScrapingItemResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='atualizado em')),
                ('sequence', models.PositiveIntegerField(verbose_name='sequência')),
                ('external_id', models.CharField(blank=True, max_length=160, verbose_name='ID externo')),
                ('original_url', models.URLField(blank=True, max_length=1200, verbose_name='URL original')),
                ('source', models.CharField(blank=True, max_length=160, verbose_name='origem da busca')),
                ('status', models.CharField(choices=[('pending', 'Pendente'), ('accepted', 'Aceito'), ('discarded', 'Descartado'), ('affiliate_failed', 'Afiliado com falha'), ('failed', 'Falhou')], default='pending', max_length=30, verbose_name='status do item')),
                ('reason_code', models.CharField(blank=True, max_length=100, verbose_name='código do motivo')),
                ('error_message', models.TextField(blank=True, verbose_name='erro')),
                ('processed_at', models.DateTimeField(verbose_name='processado em')),
                ('offer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scraping_results', to='offers.offer', verbose_name='oferta')),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='item_results', to='scraping.scrapingrun', verbose_name='execução')),
            ],
            options={
                'verbose_name': 'resultado de item coletado',
                'verbose_name_plural': 'resultados de itens coletados',
                'ordering': ['run', 'sequence'],
                'indexes': [
                    models.Index(fields=['status', 'processed_at'], name='scraping_sc_status_bc77c0_idx'),
                    models.Index(fields=['external_id'], name='scraping_sc_externa_29a7b2_idx'),
                ],
                'constraints': [
                    models.UniqueConstraint(fields=('run', 'sequence'), name='unique_scraping_item_result_sequence'),
                ],
            },
        ),
    ]
