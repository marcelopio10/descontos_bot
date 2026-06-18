from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.curation.services.blacklist import get_blacklist_terms, is_blacklisted
from apps.curation.services.selector import SelectionConfig, select_offers_for_channel
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting


class SafetyBlacklistTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
            is_active=True,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp',
            code='whatsapp_main',
            target='descontos.bot',
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )

    def _offer(self, title: str, discount: Decimal = Decimal('50.00')) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=title[:40],
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{Offer.objects.count()}-{title[:10]}',
            slug=f'oferta-{Offer.objects.count()}',
            current_price=Decimal('75.00'),
            original_price=Decimal('140.00'),
            discount_pct=discount,
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def test_safety_terms_are_enforced_even_when_panel_overrides_blacklist(self):
        Setting.objects.create(key='blacklist_terms', value='["usado"]')

        terms = get_blacklist_terms()

        self.assertIn('usado', terms)
        self.assertIn('super cavalo', terms)
        self.assertIn('torofila', terms)
        self.assertIn('vibrador sexual', terms)
        self.assertNotIn('vibrador', terms)
        self.assertIn('sensual', terms)
        self.assertIn('lingerie', terms)

    def test_adult_supplement_title_is_blacklisted(self):
        offer = self._offer('Aumenta Super Cavalo Torofila Feno Grego 60 Cápsulas Potente Sem Sabor')

        self.assertTrue(is_blacklisted(offer))

    def test_tadal_male_enhancement_title_is_blacklisted(self):
        offer = self._offer(
            'Suplemento Masculino Fila Aumenta Tamanho Natural Tadala 60 Sem Sabor',
        )

        self.assertTrue(is_blacklisted(offer))

    def test_selector_never_returns_adult_safety_blacklisted_offer(self):
        blocked = self._offer('Aumenta Super Cavalo Torofila Feno Grego 60 Cápsulas Potente Sem Sabor')
        allowed = self._offer('Tênis Adidas Runfalcon 5 Corrida De Rua Macio Masculino', Decimal('30.00'))
        Setting.objects.create(key='blacklist_terms', value='["usado"]')
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(allowed, selected)
        self.assertNotIn(blocked, selected)

    def test_selector_never_returns_tadal_male_enhancement_offer(self):
        blocked = self._offer(
            'Suplemento Masculino Fila Aumenta Tamanho Natural Tadala 60 Sem Sabor',
        )
        allowed = self._offer('Tênis Adidas Runfalcon 5 Corrida De Rua Macio Masculino', Decimal('30.00'))
        Setting.objects.create(key='blacklist_terms', value='[]')
        config = SelectionConfig(
            global_limit=5,
            marketplace_limit=5,
            min_discount_percentage=Decimal('20.00'),
            min_quality_score=0,
            priority_quality_score=0,
            exposure_quota_enabled=False,
        )

        selected = select_offers_for_channel(self.channel, config=config)

        self.assertIn(allowed, selected)
        self.assertNotIn(blocked, selected)
