from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import models

from apps._base.models import TimestampedModel
from apps.marketplaces.models import Marketplace


class Offer(TimestampedModel):
    marketplace = models.ForeignKey(
        Marketplace,
        verbose_name='marketplace',
        on_delete=models.PROTECT,
        related_name='offers',
    )
    external_id = models.CharField(
        'ID externo',
        max_length=160,
        blank=True,
    )
    title = models.CharField(
        'título',
        max_length=500,
    )
    normalized_title = models.CharField(
        'título normalizado',
        max_length=500,
    )
    offer_hash = models.CharField(
        'hash da oferta',
        max_length=64,
        unique=True,
    )
    slug = models.SlugField(
        'slug público',
        max_length=220,
        unique=True,
        db_index=True,
        null=True,
        blank=True,
        help_text='Identificador público da oferta no site.',
    )
    asin = models.CharField(
        'ASIN',
        max_length=20,
        blank=True,
        db_index=True,
        help_text='ASIN extraído da URL Amazon. Obrigatório para ofertas Amazon compliance.',
    )
    current_price = models.DecimalField(
        'preço atual',
        max_digits=12,
        decimal_places=2,
    )
    original_price = models.DecimalField(
        'preço original',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount_pct = models.DecimalField(
        'desconto (%)',
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    product_url = models.URLField(
        'URL do produto',
        max_length=1200,
    )
    affiliate_url = models.URLField(
        'URL de afiliado',
        max_length=1200,
        blank=True,
    )
    affiliate_url_override = models.URLField(
        'URL de afiliado manual',
        max_length=1200,
        blank=True,
        help_text='Link manual opcional, como amzn.to ou amzlink.to. Tem prioridade sobre a URL automática.',
    )
    image_url = models.URLField(
        'URL da imagem',
        max_length=1200,
        blank=True,
    )
    short_description = models.TextField(
        'descrição curta',
        blank=True,
        help_text='Descrição original em pt-BR para a página pública. Nunca copie texto literal da Amazon.',
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )
    raw_payload = models.JSONField(
        'payload bruto',
        default=dict,
        blank=True,
    )
    first_seen_at = models.DateTimeField(
        'visto primeiro em',
    )
    last_seen_at = models.DateTimeField(
        'visto por último em',
    )
    price_collected_at = models.DateTimeField(
        'preço coletado em',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-discount_pct', 'title']
        indexes = [
            models.Index(fields=['offer_hash']),
            models.Index(fields=['marketplace', 'external_id']),
            models.Index(fields=['is_active', 'discount_pct']),
            models.Index(fields=['last_seen_at']),
        ]
        verbose_name = 'oferta'
        verbose_name_plural = 'ofertas'

    def __str__(self):
        return self.title

    @property
    def affiliate_link(self) -> str:
        if self.affiliate_url_override:
            return self.affiliate_url_override

        if self.affiliate_url and self.marketplace.code != 'amazon':
            return self.affiliate_url

        if self.affiliate_url and self._has_compliant_amazon_affiliate_url():
            return self.affiliate_url

        if self.marketplace.code == 'amazon' and self.asin:
            tag = self.marketplace.affiliate_tag or settings.AMAZON_AFFILIATE_TAG
            return f'https://www.amazon.com.br/dp/{self.asin}?tag={tag}'

        return self.product_url

    def _has_compliant_amazon_affiliate_url(self) -> bool:
        parsed_url = urlparse(self.affiliate_url)
        host = parsed_url.netloc.lower()
        if host.endswith('amzn.to') or host.endswith('amzlink.to'):
            return True

        tag = self.marketplace.affiliate_tag or settings.AMAZON_AFFILIATE_TAG
        query = parse_qs(parsed_url.query)
        return query.get('tag') == [tag]

    @property
    def bridge_url(self) -> str:
        base_url = settings.PUBLIC_SITE_BASE_URL.rstrip('/')
        return f'{base_url}/r?slug={self.slug}'

    @property
    def absolute_saving(self) -> float:
        if self.original_price and self.current_price:
            return float(self.original_price) - float(self.current_price)
        return 0.0
