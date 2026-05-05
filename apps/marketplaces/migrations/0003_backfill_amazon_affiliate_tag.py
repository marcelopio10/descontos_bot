from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    Marketplace = apps.get_model('marketplaces', 'Marketplace')
    Marketplace.objects.filter(code='amazon', affiliate_tag='').update(
        affiliate_tag=settings.AMAZON_AFFILIATE_TAG,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('marketplaces', '0002_marketplace_affiliate_tag'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
