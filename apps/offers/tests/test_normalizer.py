from django.test import SimpleTestCase, TestCase

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import (
    OfferNormalizationError,
    build_produto_canonico_id,
    normalize_offer,
)
from apps.offers.services.title_identity import (
    normalize_editorial_title,
    strong_title_similarity,
)


class OfferNormalizerTests(TestCase):
    def test_review_count_above_database_integer_range_is_ignored(self):
        marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )

        normalized = normalize_offer(
            marketplace,
            {
                'id': 'B0TESTE123',
                'asin': 'B0TESTE123',
                'nome': 'Produto teste',
                'preco': '99,90',
                'link_direto': 'https://www.amazon.com.br/dp/B0TESTE123',
                'review_count': '999999999999999999999999 avaliações',
            },
        )

        self.assertIsNone(normalized.review_count)

    def test_review_count_within_database_integer_range_is_preserved(self):
        marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )

        normalized = normalize_offer(
            marketplace,
            {
                'id': 'B0TESTE123',
                'asin': 'B0TESTE123',
                'nome': 'Produto teste',
                'preco': '99,90',
                'link_direto': 'https://www.amazon.com.br/dp/B0TESTE123',
                'review_count': '1.234 avaliações',
            },
        )

        self.assertEqual(normalized.review_count, 1234)


class ProdutoCanonicoIdTests(TestCase):
    """Sprint 5 / achado P8: identificador best-effort de produto canônico."""

    def test_amazon_offer_uses_asin_as_canonical_id(self):
        marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )

        normalized = normalize_offer(
            marketplace,
            {
                'id': 'B0TESTE123',
                'asin': 'B0TESTE123',
                'nome': 'Produto teste',
                'preco': '99,90',
                'link_direto': 'https://www.amazon.com.br/dp/B0TESTE123',
            },
        )

        self.assertEqual(normalized.produto_canonico_id, 'amazon:B0TESTE123')

    def test_two_amazon_offers_with_same_asin_share_canonical_id(self):
        marketplace = Marketplace.objects.create(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )

        first = normalize_offer(
            marketplace,
            {
                'id': 'B0SAME1234',
                'asin': 'B0SAME1234',
                'nome': 'Produto vendedor A',
                'preco': '99,90',
                'link_direto': 'https://www.amazon.com.br/dp/B0SAME1234',
            },
        )
        second = normalize_offer(
            marketplace,
            {
                'id': 'B0SAME1234',
                'asin': 'B0SAME1234',
                'nome': 'Produto vendedor B (mesmo ASIN, preço diferente)',
                'preco': '89,90',
                'link_direto': 'https://www.amazon.com.br/dp/B0SAME1234?ref=outrovendedor',
            },
        )

        self.assertEqual(first.produto_canonico_id, second.produto_canonico_id)
        self.assertEqual(first.produto_canonico_id, 'amazon:B0SAME1234')
        # Para Amazon, normalize_offer já canonicaliza product_url para
        # /dp/{asin} (ignora querystring de vendedor/campanha), então o
        # offer_hash de duas capturas do mesmo ASIN também coincide — o
        # cenário de "duas linhas distintas, mesmo produto" que o dedup por
        # produto_canonico_id existe para resolver acontece de fato em
        # Mercado Livre/Shopee (cobertos abaixo), não em Amazon.
        self.assertEqual(first.offer_hash, second.offer_hash)

    def test_shopee_canonical_id_drops_shop_id(self):
        marketplace = Marketplace.objects.create(
            name='Shopee',
            code='shopee',
            base_url='https://shopee.com.br',
        )

        normalized = normalize_offer(
            marketplace,
            {
                'id': '111222333:999888777',
                'nome': 'Produto Shopee',
                'preco': '49,90',
                'link_direto': 'https://shopee.com.br/produto',
            },
        )

        self.assertEqual(normalized.produto_canonico_id, 'shopee:111222333')

    def test_shopee_same_item_id_different_shop_id_shares_canonical_id(self):
        marketplace = Marketplace.objects.create(
            name='Shopee',
            code='shopee',
            base_url='https://shopee.com.br',
        )

        seller_a = normalize_offer(
            marketplace,
            {'id': '111222333:1001', 'nome': 'Produto A', 'preco': '49,90', 'link_direto': 'https://shopee.com.br/produto-a'},
        )
        seller_b = normalize_offer(
            marketplace,
            {'id': '111222333:2002', 'nome': 'Produto B', 'preco': '45,00', 'link_direto': 'https://shopee.com.br/produto-b'},
        )

        self.assertEqual(seller_a.produto_canonico_id, seller_b.produto_canonico_id)
        self.assertEqual(seller_a.produto_canonico_id, 'shopee:111222333')

    def test_mercadolivre_falls_back_to_external_id_best_effort(self):
        marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )

        normalized = normalize_offer(
            marketplace,
            {
                'id': 'MLB123456789',
                'nome': 'Produto ML',
                'preco': '199,90',
                'link_direto': 'https://www.mercadolivre.com.br/MLB-123456789-produto',
            },
        )

        self.assertEqual(normalized.produto_canonico_id, 'mercadolivre:MLB123456789')

    def test_mercadolivre_product_url_is_allowlisted_and_id_bound(self):
        marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://www.mercadolivre.com.br',
        )
        for product_url in (
            'javascript:alert(1)//MLB123456789',
            'https://evil.example/MLB123456789',
            'https://www.mercadolivre.com.br/MLB-123456780-outro-produto',
            'https://www.mercadolivre.com.br/MLB-123456789/MLB-987654321',
            'https://www.mercadolivre.com.br/MLB-123456789/../MLB-987654321',
            'https://www.mercadolivre.com.br/foo/MLB-123456789/bar',
            'https://www.mercadolivre.com.br/MLB-123456789%2Fextra',
            'https://www.mercadolivre.com.br/MLB-123456789-foo-MLB987654321',
            'https://www.mercadolivre.com.br/MLB-123456789-%2e%2e',
            'https://www.mercadolivre.com.br/MLB-123456789-%3fquery',
            '\nhttps://www.mercadolivre.com.br/MLB-123456789-produto',
            'https://www.mercadolivre.com.br/MLB-123456789-produto\t',
            'https://www.mercadolivre.com.br/MLB%31',
        ):
            with self.subTest(product_url=product_url):
                with self.assertRaises(OfferNormalizationError):
                    normalize_offer(
                        marketplace,
                        {
                            'id': 'MLB123456789',
                            'nome': 'Produto ML',
                            'preco': '199,90',
                            'link_direto': product_url,
                        },
                    )

    def test_build_produto_canonico_id_returns_empty_without_any_identifier(self):
        self.assertEqual(build_produto_canonico_id('mercadolivre', '', ''), '')


class EditorialTitleIdentityTests(SimpleTestCase):
    def test_normalization_removes_formatting_and_promotional_noise(self):
        self.assertEqual(
            normalize_editorial_title(
                '  OFERTA: Tênis—Feminino, com FRETE GRÁTIS!  ',
            ),
            'tenis',
        )

    def test_normalization_removes_invisible_soft_hyphen_without_splitting_word(self):
        first = 'Micro\u00adondas Philco 20l Preto'
        second = 'Microondas Philco 20l Preto'

        self.assertEqual(
            normalize_editorial_title(first),
            'microondas philco 20l preto',
        )
        self.assertTrue(strong_title_similarity(first, second))

    def test_the_perfect_top_collides_even_with_distinct_asins(self):
        marketplace = Marketplace(
            name='Amazon',
            code='amazon',
            base_url='https://www.amazon.com.br',
        )
        first = normalize_offer(marketplace, {
            'asin': 'B0DZ34LZQB',
            'nome': 'The Perfect Top Feminino - Oferta',
            'preco': '99,90',
            'link_direto': 'https://www.amazon.com.br/dp/B0DZ34LZQB',
        })
        second = normalize_offer(marketplace, {
            'asin': 'B0DZ334MCH',
            'nome': 'THE-PERFECT TOP feminina | promoção',
            'preco': '89,90',
            'link_direto': 'https://www.amazon.com.br/dp/B0DZ334MCH',
        })

        self.assertNotEqual(first.produto_canonico_id, second.produto_canonico_id)
        self.assertTrue(strong_title_similarity(first.title, second.title))

    def test_different_products_do_not_share_editorial_identity(self):
        self.assertFalse(
            strong_title_similarity(
                'The Perfect Top Feminino - Oferta',
                'Tênis Olympikus Corre Trilha 2 Masculino',
            ),
        )

    def test_jaccard_similarity_keeps_existing_threshold_behavior(self):
        self.assertTrue(
            strong_title_similarity(
                'Camisa Torcedor 1.1 Tailand Amarela 2026',
                'Camisa Torcedor Tailand 1.1 Amarela 2026',
            ),
        )

    def test_jaccard_requires_four_tokens_on_both_sides(self):
        self.assertFalse(
            strong_title_similarity(
                'Fone Bluetooth JBL',
                'Fone Bluetooth JBL Pro',
            ),
        )
