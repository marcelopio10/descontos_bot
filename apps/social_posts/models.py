from django.db import models

from apps._base.models import TimestampedModel
from apps.offers.models import Offer


class InstagramPost(TimestampedModel):
    class Format(models.TextChoices):
        FEED = 'feed', 'Feed'
        CAROUSEL = 'carousel', 'Carrossel'
        STORY = 'story', 'Story'
        REEL = 'reel', 'Reel'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        READY = 'ready', 'Pronto'
        AWAITING_POST = 'awaiting_post', 'Aguardando publicação manual'
        POSTED = 'posted', 'Postado'
        REJECTED = 'rejected', 'Rejeitado'

    format = models.CharField(
        'formato',
        max_length=20,
        choices=Format.choices,
    )
    status = models.CharField(
        'status',
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    primary_offer = models.ForeignKey(
        Offer,
        verbose_name='oferta principal',
        on_delete=models.PROTECT,
        related_name='primary_instagram_posts',
    )
    related_offers = models.ManyToManyField(
        Offer,
        verbose_name='ofertas relacionadas',
        related_name='related_instagram_posts',
        blank=True,
    )
    asset_paths = models.JSONField(
        'caminhos dos assets',
        default=list,
        blank=True,
    )
    caption = models.TextField(
        'legenda',
        blank=True,
    )
    sticker_target_url = models.URLField(
        'URL alvo do sticker',
        max_length=1200,
        blank=True,
    )
    posted_at = models.DateTimeField(
        'postado em',
        null=True,
        blank=True,
    )
    instagram_media_id = models.CharField(
        'ID da mídia no Instagram',
        max_length=64,
        blank=True,
        db_index=True,
    )
    published_error = models.TextField(
        'erro de publicação',
        blank=True,
    )
    telegram_handoff_message_id = models.CharField(
        'ID da mensagem de handoff Telegram',
        max_length=64,
        blank=True,
        db_index=True,
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['format', 'status']),
            models.Index(fields=['posted_at']),
        ]
        verbose_name = 'post Instagram'
        verbose_name_plural = 'posts Instagram'

    def __str__(self):
        return f'{self.get_format_display()} - {self.primary_offer}'
