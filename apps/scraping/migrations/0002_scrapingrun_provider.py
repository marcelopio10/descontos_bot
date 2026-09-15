from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scraping', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='scrapingrun',
            name='provider',
            field=models.CharField(default='legacy_scraper', max_length=60, verbose_name='provider de coleta'),
        ),
    ]
