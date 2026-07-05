from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import normalize_offer


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
