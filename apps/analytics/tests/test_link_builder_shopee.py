"""Testes do branch Shopee em `link_builder.resolve_destination_url` (Sprint 4 - Tarefa 4.1).

Cobre as duas garantias exigidas pelo plano de refatoração:
1. Com `SHOPEE_AFFILIATE_ENABLED` desligado (default real de produção hoje),
   o comportamento é idêntico ao de antes desta mudança — nunca chama a API
   Shopee, sempre retorna `offer.affiliate_link`.
2. Com a flag ligada, o SubID de canal é passado corretamente para
   `resolve_affiliate_link`, e qualquer falha do client cai no fallback sem
   propagar exceção.
"""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.analytics.services.link_builder import build_tracked_url, resolve_destination_url
from apps.distribution.models import SocialChannel
from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.shopee_affiliate_client import ShopeeAffiliateError
from apps.offers.models import Offer


class ShopeeSubidLinkBuilderTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Shopee',
            code='shopee',
            base_url='https://shopee.com.br',
        )
        now = timezone.now()
        self.offer = Offer.objects.create(
            marketplace=self.marketplace,
            title='Fone Bluetooth X',
            normalized_title='fone bluetooth x',
            offer_hash='hash-shopee-link-builder-1',
            slug='fone-shopee-link-builder-1',
            current_price=Decimal('99.90'),
            product_url='https://shopee.com.br/product/123',
            affiliate_url='https://s.shopee.com.br/existing-affiliate-link',
            first_seen_at=now,
            last_seen_at=now,
        )
        self.channel = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )

    # -- flag desligada (default) -------------------------------------------

    def test_shopee_disabled_by_default_returns_affiliate_link_without_calling_api(self):
        """SHOPEE_AFFILIATE_ENABLED não setado no settings -> default False.

        Prova de segurança para produção: `resolve_destination_url` para uma
        oferta Shopee retorna exatamente `offer.affiliate_link`, sem sequer
        instanciar o client Shopee.
        """
        with mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
        ) as mocked_resolve, mock.patch(
            'apps.analytics.services.link_builder.ShopeeAffiliateClient',
        ) as mocked_client_cls:
            result = resolve_destination_url(self.offer, channel_code='wa_principal')

        self.assertEqual(result, self.offer.affiliate_link)
        mocked_resolve.assert_not_called()
        mocked_client_cls.assert_not_called()

    def test_shopee_disabled_build_tracked_url_matches_today_behavior(self):
        with mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
        ) as mocked_resolve:
            tracked = build_tracked_url(self.offer, self.channel)

        mocked_resolve.assert_not_called()
        self.assertTrue(tracked.startswith(self.offer.affiliate_link))
        self.assertIn('utm_source=whatsapp', tracked)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=False)
    def test_shopee_explicitly_disabled_returns_affiliate_link(self):
        with mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
        ) as mocked_resolve:
            result = resolve_destination_url(self.offer, channel_code='wa_principal')

        self.assertEqual(result, self.offer.affiliate_link)
        mocked_resolve.assert_not_called()

    # -- flag ligada ----------------------------------------------------------

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_shopee_enabled_passes_channel_subid_and_uses_short_timeout_client(self):
        with mock.patch(
            'apps.analytics.services.link_builder.ShopeeAffiliateClient',
        ) as mocked_client_cls, mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
        ) as mocked_resolve:
            mocked_resolve.return_value = 'https://s.shopee.com.br/tracked-wa-principal'
            result = resolve_destination_url(self.offer, channel_code='wa_principal')

        mocked_client_cls.assert_called_once_with(timeout=5, max_retries=1)
        self.assertEqual(mocked_resolve.call_count, 1)
        _args, kwargs = mocked_resolve.call_args
        self.assertEqual(kwargs['item'], {'productLink': self.offer.product_url})
        self.assertEqual(kwargs['channel_code'], 'wa_principal')
        self.assertEqual(kwargs['client'], mocked_client_cls.return_value)
        self.assertEqual(result, 'https://s.shopee.com.br/tracked-wa-principal')

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_shopee_enabled_falls_back_on_shopee_affiliate_error(self):
        with mock.patch('apps.analytics.services.link_builder.ShopeeAffiliateClient'), mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
            side_effect=ShopeeAffiliateError('boom'),
        ):
            result = resolve_destination_url(self.offer, channel_code='wa_principal')

        self.assertEqual(result, self.offer.affiliate_link)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_shopee_enabled_falls_back_on_unexpected_exception_without_propagating(self):
        with mock.patch('apps.analytics.services.link_builder.ShopeeAffiliateClient'), mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
            side_effect=RuntimeError('rede explodiu'),
        ):
            # Não deve levantar — é rede de segurança, precisa cair no fallback.
            result = resolve_destination_url(self.offer, channel_code='wa_principal')

        self.assertEqual(result, self.offer.affiliate_link)

    @override_settings(SHOPEE_AFFILIATE_ENABLED=True)
    def test_shopee_enabled_without_channel_code_does_not_call_api(self):
        with mock.patch(
            'apps.analytics.services.link_builder.resolve_affiliate_link',
        ) as mocked_resolve:
            result = resolve_destination_url(self.offer, channel_code=None)

        mocked_resolve.assert_not_called()
        self.assertEqual(result, self.offer.affiliate_link)
