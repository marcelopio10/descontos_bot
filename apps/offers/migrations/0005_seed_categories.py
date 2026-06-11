from decimal import Decimal

from django.db import migrations


SEED_CATEGORIES = [
    # code, name, weight, is_test_controlled, exposure_quota_pct
    ('casa_cozinha', 'Casa e Cozinha', 10, False, Decimal('30.00')),
    ('moda_feminina', 'Moda Feminina', 9, False, Decimal('15.00')),
    ('moda_masculina', 'Moda Masculina', 8, False, Decimal('10.00')),
    ('infantil', 'Infantil', 8, False, Decimal('15.00')),
    ('tecnologia_cotidiana', 'Tecnologia Cotidiana', 7, False, Decimal('15.00')),
    ('beleza_cuidados', 'Beleza e Cuidados Pessoais', 7, False, Decimal('10.00')),
    ('saude_suplementacao', 'Saúde e Suplementação', 5, True, Decimal('5.00')),
    ('pet', 'Pet', 4, False, None),
    ('bebidas', 'Bebidas', 3, False, None),
    ('automotivo', 'Automotivo', 3, False, None),
    ('outros', 'Outros', 2, False, None),
    ('ferramentas', 'Ferramentas', 1, False, None),
    ('construcao', 'Construção', 1, False, None),
    ('industrial', 'Industrial', 1, False, None),
]


def forwards(apps, schema_editor):
    Category = apps.get_model('offers', 'Category')
    for code, name, weight, is_test, quota in SEED_CATEGORIES:
        Category.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'weight': weight,
                'is_test_controlled': is_test,
                'exposure_quota_pct': quota,
                'is_active': True,
            },
        )


def backwards(apps, schema_editor):
    Category = apps.get_model('offers', 'Category')
    codes = [row[0] for row in SEED_CATEGORIES]
    Category.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('offers', '0004_category_offer_category_source_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
