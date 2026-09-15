from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.marketplaces.services.mercadolivre_price_resolver import PriceSnapshot
from apps.marketplaces.services.mercadolivre_product_normalizer import MercadoLivreProductNormalizer
from apps.offers.services.normalizer import OfferNormalizationError


class MercadoLivreProductNormalizerTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )
        self.price = PriceSnapshot(
            current_price=Decimal('80.00'),
            original_price=Decimal('100.00'),
            discount_pct=Decimal('20.00'),
            currency_code='BRL',
            source='sale_price',
        )

    def test_preserves_canonical_original_and_never_uses_affiliate_payload(self):
        normalized = MercadoLivreProductNormalizer().normalize(
            {
                'id': 'MLB123456789',
                'title': 'Cafeteira',
                'permalink': 'https://produto.mercadolivre.com.br/MLB-123456789-cafeteira?matt_word=x',
                'thumbnail': 'https://http2.mlstatic.com/image.jpg',
                'seller': {'id': 123, 'nickname': 'Loja'},
                'status': 'active',
                'condition': 'new',
                'available_quantity': 0,
                'affiliate_url': 'https://mercadolivre.com/sec/nao-usar',
                'secret_token': 'nao-persistir',
                '_search_provenance': {'source_kind': 'radar_brand'},
            },
            marketplace=self.marketplace,
            price=self.price,
            seller={'id': 123, 'nickname': 'Loja', 'seller_reputation': {'level_id': 'green'}},
            observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )

        self.assertEqual(normalized.product_url, 'https://produto.mercadolivre.com.br/MLB-123456789-cafeteira')
        self.assertEqual(normalized.affiliate_url, '')
        self.assertEqual(normalized.seller_id, '123')
        self.assertEqual(normalized.currency_code, 'BRL')
        self.assertEqual(normalized.available_quantity, 0)
        self.assertEqual(normalized.collection_source, 'mercadolivre_api')
        self.assertEqual(normalized.price_collected_at.year, 2026)
        self.assertNotIn('secret_token', normalized.raw_payload['api_item'])

    def test_derives_safe_url_when_permalink_is_missing(self):
        normalized = MercadoLivreProductNormalizer().normalize(
            {'id': 'MLB123456789', 'title': 'Cafeteira', 'status': 'active', 'condition': 'new'},
            marketplace=self.marketplace,
            price=self.price,
            seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
            observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(normalized.product_url, 'https://www.mercadolivre.com.br/p/MLB123456789')

    def test_rejects_external_permalink_instead_of_replacing_it(self):
        with self.assertRaises(OfferNormalizationError):
            MercadoLivreProductNormalizer().normalize(
                {
                    'id': 'MLB123456789',
                    'title': 'Cafeteira',
                    'permalink': 'https://example.com/MLB123456789',
                    'status': 'active',
                    'condition': 'new',
                },
                marketplace=self.marketplace,
                price=self.price,
                seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
                observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            )

    def test_rejects_insecure_permalink_authority(self):
        for permalink in (
            'https://user:pass@produto.mercadolivre.com.br/MLB-123456789',
            'https://produto.mercadolivre.com.br:443/MLB-123456789',
            'https://evil.mercadolivre.com.br/MLB-123456789',
            'https://produto.mercadolivre.com.br/MLB-123456780-outro-produto',
            'https://produto.mercadolivre.com.br/MLB-123456789/MLB-987654321',
            'https://produto.mercadolivre.com.br/MLB-123456789/../MLB-987654321',
            'https://produto.mercadolivre.com.br/foo/MLB-123456789/bar',
            'https://produto.mercadolivre.com.br/MLB-123456789%2Fextra',
            'https://produto.mercadolivre.com.br/MLB-123456789-foo-MLB987654321',
            'https://produto.mercadolivre.com.br/MLB-123456789-%2e%2e',
            'https://produto.mercadolivre.com.br/MLB-123456789-%3fquery',
            '\nhttps://produto.mercadolivre.com.br/MLB-123456789-cafeteira',
            'https://produto.mercadolivre.com.br/MLB-123456789-cafeteira\t',
            'https://produto.mercadolivre.com.br/MLB%31',
        ):
            with self.subTest(permalink=permalink):
                with self.assertRaises(OfferNormalizationError):
                    MercadoLivreProductNormalizer().normalize(
                        {
                            'id': 'MLB123456789',
                            'title': 'Cafeteira',
                            'permalink': permalink,
                            'status': 'active',
                            'condition': 'new',
                        },
                        marketplace=self.marketplace,
                        price=self.price,
                        seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
                        observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
                    )

    def test_rejects_invalid_available_quantity(self):
        for quantity in ('bogus', -1, 1.5, True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(OfferNormalizationError):
                    MercadoLivreProductNormalizer().normalize(
                        {
                            'id': 'MLB123456789',
                            'title': 'Cafeteira',
                            'permalink': 'https://produto.mercadolivre.com.br/MLB-123456789-cafeteira',
                            'status': 'active',
                            'condition': 'new',
                            'available_quantity': quantity,
                        },
                        marketplace=self.marketplace,
                        price=self.price,
                        seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
                        observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
                    )

    def test_rejects_malformed_permalink_without_exception_context(self):
        with self.assertRaises(OfferNormalizationError) as context:
            MercadoLivreProductNormalizer().normalize(
                {
                    'id': 'MLB123456789',
                    'title': 'Cafeteira',
                    'permalink': 'https://produto.mercadolivre.com.br:not-a-port/MLB-123456789',
                    'status': 'active',
                    'condition': 'new',
                },
                marketplace=self.marketplace,
                price=self.price,
                seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
                observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            )

        self.assertIsNone(context.exception.__cause__)
        self.assertIsNone(context.exception.__context__)

    def test_rejects_non_textual_or_blank_permalink(self):
        for permalink in (False, 0, [], {}, '   '):
            with self.subTest(permalink=permalink):
                with self.assertRaises(OfferNormalizationError):
                    MercadoLivreProductNormalizer().normalize(
                        {
                            'id': 'MLB123456789',
                            'title': 'Cafeteira',
                            'permalink': permalink,
                            'status': 'active',
                            'condition': 'new',
                        },
                        marketplace=self.marketplace,
                        price=self.price,
                        seller={'id': 123, 'seller_reputation': {'level_id': 'green'}},
                        observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
                    )
