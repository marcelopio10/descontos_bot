from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.distribution.models import SocialChannel
from apps.market_intel.models import (
    ObservedOfferLink,
    ObservedWhatsAppGroup,
    ObservedWhatsAppMessage,
)
from apps.market_intel.services import competitor_radar
from apps.panel.models import Setting


def _message(group, *, url='https://meli.la/abc123', hours_ago=1, marketplace='mercadolivre', text='oferta',
             marca='', preco=None):
    sent_at = timezone.now() - timedelta(hours=hours_ago)
    return ObservedWhatsAppMessage.objects.create(
        group=group,
        external_message_id=f'{group.id}-{url}-{hours_ago}',
        sender_hash='a' * 64,
        sent_at=sent_at,
        collected_at=sent_at,
        text=text,
        urls=[url],
        parsed_marketplace=marketplace,
        marca=marca,
        parsed_price=Decimal(str(preco)) if preco is not None else None,
    )


class CandidateSelectionTests(TestCase):
    def setUp(self):
        self.concorrente = ObservedWhatsAppGroup.objects.create(name='Grupo 039 Vitrine', jid='1@g.us')

    def test_seleciona_mensagem_com_link_do_marketplace(self):
        message = _message(self.concorrente)

        candidatos = competitor_radar.select_candidate_messages('mercadolivre')

        self.assertEqual([(m.id, u) for m, u in candidatos], [(message.id, 'https://meli.la/abc123')])

    def test_ignora_nossos_proprios_grupos(self):
        """O canal de saída também é um grupo observado — republicar a si mesmo é laço."""
        SocialChannel.objects.create(
            name='WhatsApp principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='descontos.bot',
        )
        nosso = ObservedWhatsAppGroup.objects.create(name='descontos.bot', jid='2@g.us')
        _message(nosso)

        self.assertEqual(competitor_radar.select_candidate_messages('mercadolivre'), [])

    def test_ignora_grupo_na_lista_de_exclusao(self):
        Setting.objects.create(
            key=competitor_radar.RADAR_EXCLUDED_GROUPS,
            value='["Grupo 039 Vitrine"]',
        )
        _message(self.concorrente)

        self.assertEqual(competitor_radar.select_candidate_messages('mercadolivre'), [])

    def test_ignora_link_ja_resolvido(self):
        message = _message(self.concorrente)
        ObservedOfferLink.objects.create(
            message=message,
            source_url='https://meli.la/abc123',
            marketplace_code='mercadolivre',
            status=ObservedOfferLink.Status.RESOLVED,
        )

        self.assertEqual(competitor_radar.select_candidate_messages('mercadolivre'), [])

    def test_ignora_mensagem_fora_da_janela(self):
        _message(self.concorrente, hours_ago=48)

        self.assertEqual(competitor_radar.select_candidate_messages('mercadolivre', lookback_hours=12), [])

    def test_ignora_marketplace_sem_resolvedor(self):
        """Amazon e Shopee aparecem no observer, mas não têm caminho verificado ainda."""
        _message(self.concorrente, url='https://amzn.to/xyz', marketplace='amazon')

        self.assertEqual(competitor_radar.select_candidate_messages('amazon'), [])

    def test_deduplica_mesmo_link_repetido_em_grupos_diferentes(self):
        outro = ObservedWhatsAppGroup.objects.create(name='OFERTAS SECRETAS', jid='3@g.us')
        _message(self.concorrente)
        _message(outro)

        self.assertEqual(len(competitor_radar.select_candidate_messages('mercadolivre')), 1)


class ProductLineTests(TestCase):
    """A linha do produto entre manchete, preço, cupom e CTA."""

    def test_prefere_a_linha_em_negrito(self):
        texto = (
            'FRESCA, LEVE E SEM CHEIRO; CONHEÇA A DAILY T-SHIRT DA INSIDER‼️\n'
            '_3 cores do tamanho P ao XGG_\n\n'
            '*Camiseta Daily T-shirt Insider (3 Cores)*\n\n'
            'De ~R$139~\nPor *R$56* 🔥\n\n'
            '🎟️ Cupom: *COMPENSAML*\n\n'
            '👉 *Pegar promoção:* https://meli.la/1esDf14'
        )

        self.assertEqual(competitor_radar.product_line(texto), 'Camiseta Daily T-shirt Insider (3 Cores)')

    def test_sem_negrito_vence_a_linha_mais_longa(self):
        texto = 'AS CAMISETAS MAIS VENDIDAS\n\nCamiseta Light T-shirt Insider Masculina\n\nDe R$ 189 por R$ 56'

        self.assertEqual(competitor_radar.product_line(texto), 'Camiseta Light T-shirt Insider Masculina')

    def test_mensagem_de_uma_linha_so_com_link_preco_e_cupom(self):
        """Vários grupos mandam tudo junto; o ruído vem depois do produto."""
        texto = '😱🔝🔝 https://meli.la/2Lwxh2n Cooktop 5 Bocas a Gás Electrolux Mesa de Vidro *R$ 899* Cupom: XYZ'

        self.assertEqual(
            competitor_radar.product_line(texto),
            '😱🔝🔝 Cooktop 5 Bocas a Gás Electrolux Mesa de Vidro',
        )

    def test_ignora_convite_de_grupo_mesmo_em_negrito(self):
        texto = 'Kit Mala De Viagem Bordo Pequena 10kg Abs\n*✅ Entre no nosso grupo de promos: chat.whatsapp.com/IkyT*'

        self.assertEqual(competitor_radar.product_line(texto), 'Kit Mala De Viagem Bordo Pequena 10kg Abs')

    def test_mensagem_sem_produto_nao_inventa_linha(self):
        self.assertEqual(competitor_radar.product_line('🎟️ Cupom: *COMPENSAML*\n👉 https://meli.la/x'), '')


class ConsensusOrderingTests(TestCase):
    """2026-08-21: dez grupos anunciaram a mesma camiseta Insider no mesmo dia.

    Com a fila ordenada por recência e capacidade de algumas dezenas por
    execução contra centenas de candidatos, o consenso entre grupos — o sinal
    mais forte de que a oferta importa — não influenciava nada.
    """

    CAMISETA = '*Camiseta Light T-shirt Insider*\nDe ~R$189~ Por *R${preco}*'
    TENIS = '*Tênis Olympikus Corre Trilha 2 Masculino*\nPor *R${preco}*'
    PANELA = '*Jogo de Panelas Antiaderente Mondial 5 Peças*\nPor *R${preco}*'

    def setUp(self):
        self.grupos = [
            ObservedWhatsAppGroup.objects.create(name=f'Grupo {i}', jid=f'{i}@g.us')
            for i in range(4)
        ]

    def test_oferta_repetida_em_varios_grupos_vem_antes_da_mais_recente(self):
        _message(self.grupos[0], url='https://meli.la/sozinha', hours_ago=0.1,
                 text=self.PANELA.format(preco=90), preco=90)
        for i, (grupo, preco) in enumerate(zip(self.grupos[1:], (56.00, 56.58, 56.00))):
            _message(grupo, url=f'https://meli.la/camiseta{i}', hours_ago=3,
                     text=self.CAMISETA.format(preco=preco), preco=preco)

        candidatos = competitor_radar.select_candidate_messages('mercadolivre', limit=2)
        familias = [competitor_radar.consensus_key(m)[0] for m, _ in candidatos]

        # A de consenso vem primeiro, na frente da mais recente; a segunda vaga
        # vai para outra oferta, não para uma cópia da mesma (intercalação).
        self.assertEqual(familias, ['camiseta', 'jogo_de_panelas'])

    def test_consenso_nao_depende_de_marca_conhecida(self):
        """`BRAND_PATTERNS` é lista escrita à mão; a família é heurística geral."""
        for i, grupo in enumerate(self.grupos[:3]):
            _message(grupo, url=f'https://meli.la/mash{i}', hours_ago=2,
                     text='*Kit 10 Cuecas Boxer Mash Algodão*\nPor *R$79*', preco=79)
        _message(self.grupos[3], url='https://meli.la/nike', hours_ago=0.5,
                 text='*Tênis Nike Court Lite 4 Masculino*\nPor *R$359*', preco=359)

        primeiro = competitor_radar.select_candidate_messages('mercadolivre', limit=1)[0][0]

        self.assertEqual(competitor_radar.consensus_key(primeiro)[0], 'cueca')

    def test_variacao_de_centavos_conta_como_a_mesma_oferta(self):
        a = _message(self.grupos[0], url='https://meli.la/a', text=self.CAMISETA.format(preco=56), preco=56.00)
        b = _message(self.grupos[1], url='https://meli.la/b', text=self.CAMISETA.format(preco='56,58'), preco=56.58)

        self.assertEqual(competitor_radar.consensus_key(a), competitor_radar.consensus_key(b))

    def test_mensagem_sem_produto_legivel_nao_quebra_a_ordenacao(self):
        _message(self.grupos[0], url='https://meli.la/ilegivel', hours_ago=5, text='🔥🔥🔥', preco=10)
        _message(self.grupos[1], url='https://meli.la/tenis', hours_ago=6, text=self.TENIS.format(preco=300), preco=300)

        candidatos = competitor_radar.select_candidate_messages('mercadolivre')

        self.assertEqual(len(candidatos), 2)

    def test_cluster_ja_resolvido_perde_o_desempate_mas_nao_a_fila(self):
        """Desempate, não rebaixamento: dois modelos de camiseta a R$56 são o mesmo cluster."""
        resolvida = _message(self.grupos[0], url='https://meli.la/ja', hours_ago=1,
                             text=self.CAMISETA.format(preco=56), preco=56)
        ObservedOfferLink.objects.create(
            message=resolvida,
            source_url='https://meli.la/ja',
            marketplace_code='mercadolivre',
            status=ObservedOfferLink.Status.RESOLVED,
            external_item_id='MLB1',
        )
        _message(self.grupos[1], url='https://meli.la/outro-modelo', hours_ago=1,
                 text='*Camiseta Daily T-shirt Insider*\nPor *R$56*', preco=56)
        _message(self.grupos[2], url='https://meli.la/tenis', hours_ago=4,
                 text=self.TENIS.format(preco=300), preco=300)

        familias = [competitor_radar.consensus_key(m)[0]
                    for m, _ in competitor_radar.select_candidate_messages('mercadolivre')]

        # Camiseta tem 2 grupos contra 1 do tênis, então segue na frente mesmo
        # com um irmão já resolvido — o outro modelo não pode ficar órfão.
        self.assertEqual(familias, ['camiseta', 'tenis'])

    def test_um_produto_nao_consome_a_cota_inteira(self):
        """4 grupos anunciando a mesma camiseta ocupavam as 4 primeiras posições."""
        for i, grupo in enumerate(self.grupos):
            _message(grupo, url=f'https://meli.la/camiseta{i}', hours_ago=1,
                     text=self.CAMISETA.format(preco=63), preco=63)
        _message(self.grupos[0], url='https://meli.la/tenis', hours_ago=2,
                 text=self.TENIS.format(preco=338), preco=338)
        _message(self.grupos[1], url='https://meli.la/panela', hours_ago=2,
                 text=self.PANELA.format(preco=35), preco=35)

        familias = [competitor_radar.consensus_key(m)[0]
                    for m, _ in competitor_radar.select_candidate_messages('mercadolivre', limit=3)]

        self.assertEqual(sorted(familias), ['camiseta', 'jogo_de_panelas', 'tenis'])


class ResolutionTests(TestCase):
    def setUp(self):
        self.group = ObservedWhatsAppGroup.objects.create(name='Grupo 039 Vitrine', jid='1@g.us')
        self.message = _message(self.group)

    def _scraper(self, payload):
        scraper = MagicMock(blocked=False)
        scraper.scrape_social_card.return_value = payload
        return scraper

    def test_grava_anuncio_resolvido(self):
        payload = {
            'id': 'MLB6513391130',
            'nome': 'Kit 3 Cuecas Boxer Calvin Klein',
            'preco': 185.99,
            'preco_original': 329.0,
            'desconto_pct': 43,
            'link_direto': 'https://www.mercadolivre.com.br/kit-3-cuecas/up/MLBU2742581594',
            'link_afiliado': 'https://mercadolivre.com/sec/nosso',
            'imagem': 'https://http2.mlstatic.com/imagem-O.webp',
            'vendedor': 'Mercado Livre',
        }

        stats = competitor_radar.resolve_candidates(scraper=self._scraper(payload), sleep=False)

        link = ObservedOfferLink.objects.get()
        self.assertEqual(stats['resolved'], 1)
        self.assertEqual(link.status, ObservedOfferLink.Status.RESOLVED)
        self.assertEqual(link.external_item_id, 'MLB6513391130')
        self.assertEqual(link.current_price, Decimal('185.99'))
        self.assertEqual(link.affiliate_url, 'https://mercadolivre.com/sec/nosso')
        self.assertIsNotNone(link.resolved_at)

    def test_link_sem_card_vira_falha_registrada(self):
        """Falha precisa ficar gravada: sem isso o mesmo link morto volta todo ciclo."""
        stats = competitor_radar.resolve_candidates(scraper=self._scraper(None), sleep=False)

        link = ObservedOfferLink.objects.get()
        self.assertEqual(stats['failed'], 1)
        self.assertEqual(stats['no_discount'], 1)
        self.assertEqual(link.status, ObservedOfferLink.Status.FAILED)
        self.assertIn('desconto de página', link.failure_reason)

    def test_excecao_em_um_link_nao_derruba_o_lote(self):
        _message(self.group, url='https://meli.la/segundo')
        scraper = MagicMock(blocked=False)
        scraper.scrape_social_card.side_effect = [RuntimeError('timeout'), {'id': 'MLB1', 'nome': 'Tênis', 'preco': 100.0}]

        stats = competitor_radar.resolve_candidates(scraper=scraper, sleep=False)

        self.assertEqual(stats['candidates'], 2)
        self.assertEqual(stats['resolved'], 1)
        self.assertEqual(stats['failed'], 1)
        self.assertIn('RuntimeError', ObservedOfferLink.objects.get(status='failed').failure_reason)

    def test_dry_run_nao_grava(self):
        competitor_radar.resolve_candidates(scraper=self._scraper({'id': 'MLB1', 'nome': 'X', 'preco': 10.0}), dry_run=True, sleep=False)

        self.assertEqual(ObservedOfferLink.objects.count(), 0)

    def test_para_quando_o_scraper_e_bloqueado(self):
        _message(self.group, url='https://meli.la/segundo')
        scraper = MagicMock(blocked=True)

        stats = competitor_radar.resolve_candidates(scraper=scraper, sleep=False)

        scraper.scrape_social_card.assert_not_called()
        self.assertEqual(stats['resolved'], 0)


class PayloadTests(TestCase):
    def setUp(self):
        self.group = ObservedWhatsAppGroup.objects.create(name='Grupo 039 Vitrine', jid='1@g.us')

    def _link(self, item_id, *, hours_ago=1, **kwargs):
        message = _message(self.group, url=f'https://meli.la/{item_id}-{hours_ago}', hours_ago=hours_ago)
        defaults = {
            'marketplace_code': 'mercadolivre',
            'status': ObservedOfferLink.Status.RESOLVED,
            'external_item_id': item_id,
            'title': f'Produto {item_id}',
            'current_price': Decimal('100.00'),
            'original_price': Decimal('200.00'),
            'discount_pct': Decimal('50'),
            'resolved_url': f'https://www.mercadolivre.com.br/{item_id}',
            'affiliate_url': f'https://mercadolivre.com/sec/{item_id}',
            'resolved_at': timezone.now() - timedelta(hours=hours_ago),
        }
        defaults.update(kwargs)
        return ObservedOfferLink.objects.create(message=message, source_url=message.urls[0], **defaults)

    def test_payload_tem_o_formato_do_scraper_e_proveniencia_do_radar(self):
        self._link('MLB1')

        payload = competitor_radar.build_radar_payloads('mercadolivre')[0]

        self.assertEqual(payload['id'], 'MLB1')
        self.assertEqual(payload['preco'], 100.0)
        self.assertEqual(payload['desconto_pct'], 50)
        self.assertEqual(payload['link_afiliado'], 'https://mercadolivre.com/sec/MLB1')
        self.assertEqual(payload['search_provenance'], {
            'source_kind': 'competitor_radar',
            'marketplace': 'mercadolivre',
        })

    def test_descarta_resolucao_velha(self):
        """Preço vem do card no momento da resolução; velho demais não se publica."""
        self._link('MLB1', hours_ago=30)

        self.assertEqual(competitor_radar.build_radar_payloads('mercadolivre', freshness_hours=6), [])

    def test_um_payload_por_anuncio(self):
        self._link('MLB1', hours_ago=1)
        self._link('MLB1', hours_ago=2)

        payloads = competitor_radar.build_radar_payloads('mercadolivre')

        self.assertEqual([p['id'] for p in payloads], ['MLB1'])

    def test_ignora_falha_e_link_sem_item(self):
        self._link('MLB1', status=ObservedOfferLink.Status.FAILED)
        self._link('', hours_ago=2)

        self.assertEqual(competitor_radar.build_radar_payloads('mercadolivre'), [])

    def test_aplica_teto_de_preco_da_categoria(self):
        """Sem isto o radar entra por fora das regras que valem para a coleta própria."""
        self._link(
            'MLB_MONITOR',
            title='Monitor Gamer LG UltraGear Curvo 34" QuadHD',
            current_price=Decimal('1756.00'),
            original_price=Decimal('2665.00'),
            discount_pct=Decimal('34'),
        )

        self.assertEqual(competitor_radar.build_radar_payloads('mercadolivre'), [])

    def test_aplica_desconto_minimo_da_categoria(self):
        self._link(
            'MLB_MEIA',
            title='Kit 12 Pares Meia Soquete Cano Curto Preto',
            current_price=Decimal('25.00'),
            original_price=Decimal('27.00'),
            discount_pct=Decimal('9'),
        )

        self.assertEqual(competitor_radar.build_radar_payloads('mercadolivre'), [])

    def test_oferta_dentro_das_regras_passa(self):
        self._link(
            'MLB_TENIS',
            title='Tênis Reserva R-ollie Masculino Urbano Casual',
            current_price=Decimal('299.00'),
            original_price=Decimal('499.00'),
            discount_pct=Decimal('40'),
        )

        self.assertEqual([p['id'] for p in competitor_radar.build_radar_payloads('mercadolivre')], ['MLB_TENIS'])

    def test_desligado_por_padrao(self):
        self.assertFalse(competitor_radar.radar_enabled())
        Setting.objects.create(key=competitor_radar.RADAR_ENABLED_FLAG, value='true')
        self.assertTrue(competitor_radar.radar_enabled())


class CoverageReportTests(TestCase):
    def test_relatorio_separa_inedito_do_que_ja_temos(self):
        from apps.marketplaces.models import Marketplace
        from apps.offers.models import Offer

        group = ObservedWhatsAppGroup.objects.create(name='Grupo 039 Vitrine', jid='1@g.us')
        marketplace = Marketplace.objects.create(code='mercadolivre', name='Mercado Livre')
        Offer.objects.create(
            marketplace=marketplace,
            external_id='MLB_JA_TEMOS',
            title='Já temos',
            normalized_title='ja temos',
            offer_hash='hash-1',
            current_price=Decimal('10.00'),
            product_url='https://www.mercadolivre.com.br/ja-temos',
            first_seen_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        for item_id in ('MLB_JA_TEMOS', 'MLB_NOVO'):
            message = _message(group, url=f'https://meli.la/{item_id}')
            ObservedOfferLink.objects.create(
                message=message,
                source_url=message.urls[0],
                marketplace_code='mercadolivre',
                status=ObservedOfferLink.Status.RESOLVED,
                external_item_id=item_id,
                resolved_at=timezone.now(),
            )

        report = competitor_radar.build_coverage_report(lookback_hours=24)

        self.assertEqual(report['anuncios_distintos'], 2)
        self.assertEqual(report['ja_no_nosso_pool'], 1)
        self.assertEqual(report['inedito_para_nos'], 1)
