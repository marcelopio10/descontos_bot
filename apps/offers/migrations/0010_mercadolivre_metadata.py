from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offers', '0009_pricehistoryentry'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='seller_id',
            field=models.CharField(blank=True, max_length=40, verbose_name='ID do vendedor'),
        ),
        migrations.AddField(
            model_name='offer',
            name='seller_name',
            field=models.CharField(blank=True, max_length=200, verbose_name='nome do vendedor'),
        ),
        migrations.AddField(
            model_name='offer',
            name='currency_code',
            field=models.CharField(blank=True, max_length=10, verbose_name='moeda'),
        ),
        migrations.AddField(
            model_name='offer',
            name='listing_status',
            field=models.CharField(blank=True, max_length=40, verbose_name='status do anúncio'),
        ),
        migrations.AddField(
            model_name='offer',
            name='item_condition',
            field=models.CharField(blank=True, max_length=40, verbose_name='condição do item'),
        ),
        migrations.AddField(
            model_name='offer',
            name='available_quantity',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='quantidade disponível'),
        ),
        migrations.AddField(
            model_name='offer',
            name='collection_source',
            field=models.CharField(blank=True, default='', max_length=80, verbose_name='origem da coleta'),
        ),
    ]
