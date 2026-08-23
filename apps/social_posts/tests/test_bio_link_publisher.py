"""Cobertura da vitrine do link da bio (item 12 da Onda 2, 2026-08-23).

O defeito que estes testes impedem de voltar: `links.json` ordenado por
`-discount_pct`. Era a vitrine de aquisição do Instagram mostrando "O Idiota" a
R$ 1,99 com 97% de desconto e uma caneta de bordado russa — ordenar por desconto
premia exatamente o desconto falso que o `quality_score` existe para punir.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Category, Offer
from apps.social_posts.services.bio_link_publisher import build_links_payload


class BioLinkVitrineTests(TestCase):
    def setUp(self):
        self.ml, _ = Marketplace.objects.get_or_create(
            code='mercadolivre', defaults={'name': 'Mercado Livre'},
        )
        self.shopee, _ = Marketplace.objects.get_or_create(
            code='shopee', defaults={'name': 'Shopee'},
        )
        self.categoria, _ = Category.objects.get_or_create(
            code='moda_masculina', defaults={'name': 'Moda Masculina', 'weight': 8},
        )

    def _offer(self, external_id, title, price, discount, marketplace=None, **extra):
        agora = timezone.now()
        return Offer.objects.create(
            marketplace=marketplace or self.ml,
            category=self.categoria,
            external_id=external_id,
            title=title,
            normalized_title=title.lower(),
            offer_hash=f'hash-{external_id}',
            slug=f'slug-{external_id}',
            current_price=Decimal(price),
            original_price=Decimal(price) * 3,
            discount_pct=Decimal(discount),
            product_url=f'https://exemplo/{external_id}',
            image_url='https://exemplo/img.jpg',
            is_active=True,
            first_seen_at=agora - timedelta(days=2),
            last_seen_at=agora,
            **extra,
        )

    def test_nao_repete_familia_de_produto(self):
        """Três tênis seguidos é o que o visitante enxerga — e foi o que a
        seleção por desconto produzia."""
        for i in range(4):
            self._offer(f'T{i}', f'Tênis Casual Conforto Modelo {i}', '99.90', '60')
        self._offer('C1', 'Camiseta Básica Algodão Premium', '69.90', '45')
        self._offer('V1', 'Vestido Longo Casual Feminino', '79.90', '50')

        payload = build_links_payload(count=3)

        titulos = [item['title'] for item in payload['items']]
        tenis = [t for t in titulos if 'Tênis' in t]
        self.assertLessEqual(len(tenis), 1, titulos)

    def test_vitrine_curta_e_preferivel_a_vitrine_vazia(self):
        """Com poucas ofertas aprovadas, entrega o que tem em vez de estourar."""
        self._offer('U1', 'Camiseta Básica Algodão Premium', '69.90', '45')

        payload = build_links_payload(count=5)

        self.assertEqual(len(payload['items']), 1)

    def test_oferta_fora_da_janela_de_recencia_nao_entra(self):
        antiga = self._offer('A1', 'Camiseta Básica Algodão Premium', '69.90', '45')
        Offer.objects.filter(pk=antiga.pk).update(
            last_seen_at=timezone.now() - timedelta(days=30),
        )
        self._offer('N1', 'Vestido Longo Casual Feminino', '79.90', '50')

        payload = build_links_payload(count=5)

        ids = [item['id'] for item in payload['items']]
        self.assertNotIn(antiga.id, ids)

    def test_sem_oferta_publicavel_levanta_erro(self):
        """O site_publisher trata esta exceção e mantém o links.json anterior —
        vitrine velha é melhor que vitrine vazia."""
        with self.assertRaises(ValueError):
            build_links_payload(count=5)

    def test_diversifica_marketplace_quando_da(self):
        self._offer('M1', 'Camiseta Básica Algodão Premium', '69.90', '45', marketplace=self.ml)
        self._offer('M2', 'Calça Jeans Masculina Slim', '129.90', '40', marketplace=self.ml)
        self._offer('M3', 'Jaqueta Corta Vento Masculina', '149.90', '45', marketplace=self.ml)
        self._offer('S1', 'Vestido Longo Casual Feminino', '79.90', '50', marketplace=self.shopee)

        payload = build_links_payload(count=3)

        marketplaces = {item['marketplace_code'] for item in payload['items']}
        self.assertIn('shopee', marketplaces, payload['items'])
