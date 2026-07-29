from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('social_posts', '0003_instagrampost_telegram_handoff_message_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='instagrampost',
            name='instagram_container_id',
            field=models.CharField(blank=True, db_index=True, max_length=128, verbose_name='ID do container no Instagram'),
        ),
        migrations.AddField(
            model_name='instagrampost',
            name='instagram_permalink',
            field=models.URLField(blank=True, max_length=1200, verbose_name='permalink no Instagram'),
        ),
        migrations.AddField(
            model_name='instagrampost',
            name='publish_attempts',
            field=models.PositiveIntegerField(default=0, verbose_name='tentativas de publicação'),
        ),
        migrations.AddField(
            model_name='instagrampost',
            name='publish_state',
            field=models.CharField(default='not_started', max_length=20, verbose_name='estado técnico da publicação'),
        ),
        migrations.AddField(
            model_name='instagrampost',
            name='publication_receipt',
            field=models.JSONField(blank=True, default=dict, verbose_name='recibo de publicação'),
        ),
    ]