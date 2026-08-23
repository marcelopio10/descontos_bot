"""Cobertura do publicador em lote do Instagram (item 10 da Onda 2, 2026-08-23).

O Composio é **sempre** mockado: nenhum teste pode publicar de verdade na conta
do dono, mesmo com a connected account válida no ambiente.

O que estes testes protegem:

1. **Simulação é o padrão.** Sem `--confirm-production`, nada é publicado — a
   conta é real e de terceiro.
2. **Backlog velho não vai ao ar.** Dos 89 posts parados desde junho, 82 são de
   oferta que saiu do ar; publicar preço morto queima a conta que deveria trazer
   público.
3. **A cota diária conta o que foi publicado, não o que foi gerado.** A
   `politica_cadencia` responde outra pergunta, e usá-la aqui liberaria a fila
   inteira num dia.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import PublishResult


class PublicarLoteTestCase(TestCase):
    def setUp(self):
        self.marketplace, _ = Marketplace.objects.get_or_create(
            code='shopee', defaults={'name': 'Shopee'},
        )

    def _offer(self, external_id='X1', ativa=True, vista_ha_dias=0) -> Offer:
        agora = timezone.now()
        return Offer.objects.create(
            marketplace=self.marketplace,
            external_id=external_id,
            title='Camiseta Básica Algodão',
            normalized_title='camiseta basica algodao',
            offer_hash=f'hash-{external_id}',
            current_price=Decimal('59.90'),
            discount_pct=Decimal('40'),
            product_url=f'https://exemplo/{external_id}',
            is_active=ativa,
            first_seen_at=agora - timedelta(days=10),
            last_seen_at=agora - timedelta(days=vista_ha_dias),
        )

    def _post(self, offer, formato=InstagramPost.Format.STORY, criado_ha_dias=0):
        post = InstagramPost.objects.create(
            format=formato,
            status=InstagramPost.Status.AWAITING_POST,
            primary_offer=offer,
            caption='legenda',
            asset_paths=['/tmp/asset.jpg'],
        )
        if criado_ha_dias:
            InstagramPost.objects.filter(pk=post.pk).update(
                created_at=timezone.now() - timedelta(days=criado_ha_dias),
            )
            post.refresh_from_db()
        return post


@patch('apps.social_posts.management.commands.publicar_instagram_lote.publish_post')
class SimulacaoTests(PublicarLoteTestCase):
    def test_sem_confirmacao_nao_publica(self, mock_publish):
        self._post(self._offer())

        call_command('publicar_instagram_lote', '--limit', '5')

        mock_publish.assert_not_called()
        self.assertEqual(
            InstagramPost.objects.filter(status=InstagramPost.Status.AWAITING_POST).count(),
            1,
        )

    def test_com_confirmacao_publica_respeitando_o_limite(self, mock_publish):
        mock_publish.return_value = PublishResult(
            container_id='c1', media_id='m1', asset_path='/tmp/asset.jpg',
        )
        for i in range(3):
            self._post(self._offer(external_id=f'O{i}'))

        call_command('publicar_instagram_lote', '--limit', '2', '--confirm-production')

        self.assertEqual(mock_publish.call_count, 2)


@patch('apps.social_posts.management.commands.publicar_instagram_lote.publish_post')
class FilaVelhaTests(PublicarLoteTestCase):
    def test_post_antigo_e_descartado(self, mock_publish):
        self._post(self._offer(), criado_ha_dias=30)

        call_command('publicar_instagram_lote', '--limit', '5', '--confirm-production')

        mock_publish.assert_not_called()

    def test_post_de_oferta_inativa_e_descartado(self, mock_publish):
        self._post(self._offer(ativa=False))

        call_command('publicar_instagram_lote', '--limit', '5', '--confirm-production')

        mock_publish.assert_not_called()

    def test_post_de_oferta_fora_da_janela_de_recencia_e_descartado(self, mock_publish):
        self._post(self._offer(vista_ha_dias=45))

        call_command('publicar_instagram_lote', '--limit', '5', '--confirm-production')

        mock_publish.assert_not_called()


@patch('apps.social_posts.management.commands.publicar_instagram_lote.publish_post')
class CotaDiariaTests(PublicarLoteTestCase):
    def test_cota_conta_o_que_ja_foi_publicado_hoje(self, mock_publish):
        """Três stories já publicados hoje esgotam o teto padrão de 3/dia."""
        mock_publish.return_value = PublishResult(
            container_id='c1', media_id='m1', asset_path='/tmp/asset.jpg',
        )
        for i in range(3):
            post = self._post(self._offer(external_id=f'P{i}'))
            post.status = InstagramPost.Status.POSTED
            post.posted_at = timezone.now()
            post.save(update_fields=['status', 'posted_at'])
        self._post(self._offer(external_id='NOVO'))

        call_command('publicar_instagram_lote', '--limit', '5', '--confirm-production')

        mock_publish.assert_not_called()

    def test_falha_de_publicacao_nao_consome_cota_nem_derruba_o_lote(self, mock_publish):
        from apps.social_posts.services.composio_publisher import ComposioPublishError

        mock_publish.side_effect = [
            ComposioPublishError('falhou', stage='create'),
            PublishResult(container_id='c2', media_id='m2', asset_path='/tmp/asset.jpg'),
        ]
        self._post(self._offer(external_id='A'))
        self._post(self._offer(external_id='B'))

        call_command('publicar_instagram_lote', '--limit', '5', '--confirm-production')

        self.assertEqual(mock_publish.call_count, 2)
        self.assertEqual(
            InstagramPost.objects.filter(status=InstagramPost.Status.REJECTED).count(),
            1,
        )
