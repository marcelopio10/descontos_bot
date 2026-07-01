from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.offers.services.site_publisher import _get_publishable_offers
from apps.panel.models import Setting


class SitePublisherSafetyTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
            is_active=True,
        )

    def _offer(self, title: str, slug: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=slug,
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{slug}',
            slug=slug,
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=Decimal('46.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_publishable_offers_exclude_safety_blacklisted_titles(self):
        Setting.objects.create(key='blacklist_terms', value='[]')
        blocked = self._offer(
            'Aumenta Super Cavalo Torofila Feno Grego 60 Cápsulas Potente Sem Sabor',
            'adulto',
        )
        allowed = self._offer('Cafeteira Elétrica Inox 30 Cafés', 'cafeteira')

        publishable = list(_get_publishable_offers())

        self.assertIn(allowed, publishable)
        self.assertNotIn(blocked, publishable)

    def test_publishable_offers_exclude_editorially_irrelevant_training_head(self):
        Setting.objects.create(key='blacklist_terms', value='[]')
        blocked = self._offer(
            'Cabeça P/ Treino Com Barba Lisa Masculina 100% Natural C Suporte Cor Castanho Zhang Hair',
            'cabeca-treino',
        )
        allowed = self._offer('Cafeteira Elétrica Inox 30 Cafés', 'cafeteira')

        publishable = list(_get_publishable_offers())

        self.assertIn(allowed, publishable)
        self.assertNotIn(blocked, publishable)
