from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.offers.services.normalizer import normalize_offer
from apps.offers.services.repository import save_normalized_offer


class ProvenancePersistenceTests(TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(name='Mercado Livre', code='mercadolivre', base_url='https://mercadolivre.test')

    def _payload(self, source_kind, query):
        return {
            'id': 'ML-1',
            'nome': 'Nike tenis revolution',
            'preco': '199,90',
            'preco_original': '399,90',
            'link_direto': 'https://mercadolivre.test/ML-1',
            'search_provenance': {
                'source_kind': source_kind,
                'query_text': query,
                'marketplace': 'mercadolivre',
            },
        }

    def test_update_preserves_current_and_previous_search_provenance(self):
        offer, _ = save_normalized_offer(normalize_offer(self.marketplace, self._payload('generic_fallback', 'legado')))
        offer, _ = save_normalized_offer(normalize_offer(self.marketplace, self._payload('radar_brand', 'nike tenis')))

        self.assertEqual(offer.raw_payload['search_provenance']['source_kind'], 'radar_brand')
        history = offer.raw_payload['search_provenance_history']
        self.assertIn({'source_kind': 'generic_fallback', 'query_text': 'legado', 'marketplace': 'mercadolivre'}, history)
        self.assertIn({'source_kind': 'radar_brand', 'query_text': 'nike tenis', 'marketplace': 'mercadolivre'}, history)
