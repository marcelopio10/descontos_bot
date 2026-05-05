import re

from django.db import migrations
from django.utils.text import slugify


ASIN_RE = re.compile(r'/dp/([A-Z0-9]{10})')


def forwards(apps, schema_editor):
    Offer = apps.get_model('offers', 'Offer')

    for offer in Offer.objects.select_related('marketplace').all():
        update_fields = []

        if not offer.slug:
            base = slugify(offer.normalized_title or offer.title or 'oferta')[:200]
            offer.slug = f'{base or "oferta"}-{offer.id}'
            update_fields.append('slug')

        if offer.marketplace.code == 'amazon' and not offer.asin:
            match = ASIN_RE.search(offer.product_url or '')
            if match:
                offer.asin = match.group(1)
                update_fields.append('asin')

        if not offer.price_collected_at:
            offer.price_collected_at = offer.last_seen_at
            update_fields.append('price_collected_at')

        if update_fields:
            offer.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('offers', '0002_offer_affiliate_url_override_offer_asin_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
