from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.curation.services.ad_disclosure import (
    AD_DISCLOSURE_TAG,
    ad_disclosure_prefix,
    assert_copy_compliant,
    find_blocked_copy,
    requires_ad_disclosure,
)
from apps.curation.services.message_builder import build_message
from apps.curation.services.telegram_message_builder import build_telegram_payload
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer


class AdDisclosureHelperTests(SimpleTestCase):
    def test_requires_disclosure_disabled_for_offer_captions(self):
        self.assertFalse(requires_ad_disclosure('shopee'))
        self.assertFalse(requires_ad_disclosure('amazon'))
        self.assertFalse(requires_ad_disclosure(''))

    def test_prefix_absent_for_offer_captions(self):
        self.assertEqual(ad_disclosure_prefix('shopee'), '')
        self.assertEqual(ad_disclosure_prefix('mercadolivre'), '')

    def test_find_blocked_copy(self):
        self.assertIn('você ganhou', find_blocked_copy('PARABÉNS, VOCÊ GANHOU um prêmio'))
        self.assertEqual(find_blocked_copy('Oferta honesta com desconto real'), [])

    def test_assert_copy_compliant_raises_on_clickbait(self):
        with self.assertRaises(ValueError):
            assert_copy_compliant('clique obrigatório agora', 'shopee')

    def test_assert_copy_compliant_does_not_require_tag_for_shopee_offer_caption(self):
        assert_copy_compliant('Oferta sem selo', 'shopee')
        assert_copy_compliant(f'{AD_DISCLOSURE_TAG} Oferta com selo', 'shopee')


class DisclosureInBuildersTests(TestCase):
    def _make_offer(self, marketplace, offer_hash):
        now = timezone.now()
        return Offer.objects.create(
            marketplace=marketplace,
            title='Fone Bluetooth X',
            normalized_title='fone bluetooth x',
            offer_hash=offer_hash,
            slug=f'fone-{offer_hash}',
            current_price=Decimal('199.90'),
            original_price=Decimal('399.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://shopee.com.br/product/111',
            affiliate_url='https://s.shopee.com.br/abc',
            image_url='https://cf.shopee.com.br/img.jpg',
            first_seen_at=now,
            last_seen_at=now,
        )

    def _channel(self, channel_type='whatsapp'):
        return SocialChannel.objects.create(
            name='Canal',
            code=f'canal_{channel_type}',
            channel_type=channel_type,
            target='grupo',
            is_enabled=True,
            link_strategy='affiliate_direct',
        )

    def test_whatsapp_message_has_no_hashtag_disclosure_for_shopee(self):
        shopee = Marketplace.objects.create(
            name='Shopee', code='shopee', base_url='https://shopee.com.br', affiliate_enabled=True,
        )
        offer = self._make_offer(shopee, 'hash-shopee-1')
        message = build_message(offer, self._channel('whatsapp'))
        self.assertNotIn(AD_DISCLOSURE_TAG, message)
        self.assertFalse(message.startswith(AD_DISCLOSURE_TAG))

    def test_telegram_caption_has_no_hashtag_disclosure_for_shopee(self):
        shopee = Marketplace.objects.create(
            name='Shopee', code='shopee', base_url='https://shopee.com.br', affiliate_enabled=True,
        )
        offer = self._make_offer(shopee, 'hash-shopee-2')
        payload = build_telegram_payload(offer, self._channel('telegram_channel'))
        self.assertNotIn(AD_DISCLOSURE_TAG, payload.caption)

    def test_non_shopee_message_has_no_disclosure(self):
        ml = Marketplace.objects.create(
            name='Mercado Livre', code='mercadolivre', base_url='https://www.mercadolivre.com.br',
        )
        offer = self._make_offer(ml, 'hash-ml-1')
        message = build_message(offer, self._channel('whatsapp'))
        self.assertNotIn(AD_DISCLOSURE_TAG, message)
