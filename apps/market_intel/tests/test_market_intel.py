import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.market_intel.models import ObservedWhatsAppGroup, ObservedWhatsAppMessage
from apps.marketplaces.models import Marketplace
from apps.offers.models import Category, Offer
from apps.market_intel.services.parser import parse_observed_message
from apps.market_intel.services.reports import (
    build_cadencia_e_timing,
    build_copy_e_formato,
    build_cobertura,
    build_daily_report_payload,
    build_intelligent_insights,
    build_marcas_por_categoria,
    build_mecanica_preco,
    build_marketplace_detalhado,
    build_sinais_engajamento,
    generate_daily_report,
)


class MarketIntelParserV1Tests(TestCase):
    """Regression tests: v1 parser outputs remain unchanged."""

    def test_parser_extracts_marketplace_price_coupon_and_labels(self):
        parsed = parse_observed_message(
            'Corre! Air Fryer por R$ 199,90 com cupom CASA10 https://amzn.to/oferta'
        )
        self.assertEqual(parsed['marketplace'], 'amazon')
        self.assertEqual(parsed['price'], '199.90')
        self.assertEqual(parsed['coupon'], 'CASA10')
        self.assertIn('urgencia', parsed['labels'])
        self.assertIn('cupom', parsed['labels'])
        self.assertIn('ate_300', parsed['labels'])
        self.assertIn('termo:air fryer', parsed['scraper_hints'])

    def test_parser_calculates_discount_when_original_price_exists(self):
        parsed = parse_observed_message('De R$ 299,90 por R$ 199,90 https://mercadolivre.com.br/oferta')
        self.assertEqual(parsed['marketplace'], 'mercadolivre')
        self.assertEqual(parsed['price'], '199.90')
        self.assertEqual(parsed['original_price'], '299.90')
        self.assertEqual(parsed['discount_pct'], '33.34')

    def test_parser_extracts_coupon_after_label_punctuation_or_connector(self):
        examples = {
            'Cupom: TESTE10': 'TESTE10',
            'cupom - TESTE10': 'TESTE10',
            'use o cupom TESTE10': 'TESTE10',
            'aplique o cupom TESTE10': 'TESTE10',
        }
        for text, expected_coupon in examples.items():
            with self.subTest(text=text):
                parsed = parse_observed_message(text)
                self.assertEqual(parsed['coupon'], expected_coupon)
                self.assertIn('cupom', parsed['labels'])

    def test_parser_matches_brand_by_whole_word(self):
        """`'lg' in normalized` casava dentro de "algodão".

        Em 2026-08-21 havia 297 mensagens marcadas como marca `lg` na janela de 7
        dias, boa parte camiseta de algodão. O campo alimenta relatório e
        priorização do radar.
        """
        self.assertEqual(parse_observed_message('Kit 3 Camisetas Algodão Dia Dia')['marca'], '')
        self.assertEqual(parse_observed_message('Smart TV 50" LG 4K Ultra HD')['marca'], 'lg')

    def test_parser_recognizes_apparel_brands_from_the_observed_groups(self):
        """`insider` faltava, e era a marca que todos os grupos anunciavam."""
        examples = {
            'Camiseta Insider Light T-Shirt (3 Cores)': 'insider',
            'Kit 6 Cuecas Lupo Boxer Sem Costura': 'lupo',
            'Tênis Esportivo Corrida Fila Fastpace': 'fila',
            'Kit 2 Cuecas Boxer Calvin Klein': 'calvin klein',
            'Whey Protein Growth Supplements 1kg': 'growth',
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(parse_observed_message(text)['marca'], expected)

    def test_parser_extracts_coupon_wrapped_in_whatsapp_formatting(self):
        """Formato dominante nos grupos observados: `🎟️ Cupom: *COMPENSAML*`.

        O `*` de negrito interrompia o casamento e o código se perdia — justamente
        o campo que explica o preço anunciado, já que a oferta do concorrente
        costuma nascer do cupom, não do desconto de página.
        """
        examples = {
            '🎟️ Cupom: *COMPENSAML*': 'COMPENSAML',
            '🎟️ *Cupom:* *PROMOTEC*': 'PROMOTEC',
            'Use o Cupom: _COMPENSAML_': 'COMPENSAML',
            'Cupom ~TESTE10~': 'TESTE10',
        }
        for text, expected_coupon in examples.items():
            with self.subTest(text=text):
                self.assertEqual(parse_observed_message(text)['coupon'], expected_coupon)


class MarketIntelParserV2PriceTests(TestCase):
    """P0-2: Price mechanics extraction tests."""

    def test_pix_discount_label(self):
        parsed = parse_observed_message('Fone Bluetooth R$ 99,90 com 5% de desconto no Pix https://amzn.to/x')
        self.assertTrue(parsed['pix'])
        self.assertEqual(parsed['pix_desconto_pct'], '5.00')
        self.assertIn('pix', parsed['labels'])

    def test_parcelamento_sem_juros(self):
        parsed = parse_observed_message('Notebook 12x de R$ 299,90 s/ juros https://mercadolivre.com.br/x')
        self.assertEqual(parsed['parcelamento'], 12)
        self.assertTrue(parsed['parcelado_sem_juros'])
        self.assertIn('parcelado_sem_juros', parsed['labels'])

    def test_parcelamento_com_juros(self):
        parsed = parse_observed_message('TV 10x de R$ 499,90 https://mercadolivre.com.br/x')
        self.assertEqual(parsed['parcelamento'], 10)
        # Without "sem juros" indicator, parcelado_sem_juros is falsy
        self.assertFalse(parsed['parcelado_sem_juros'] or False)

    def test_cashback_pct(self):
        parsed = parse_observed_message('Perfume R$ 199 5% de cashback https://shopee.com.br/x')
        self.assertTrue(parsed['cashback'])
        self.assertIn('cashback', parsed['labels'])

    def test_menor_preco(self):
        parsed = parse_observed_message('Cafeteira menor preço da internet R$ 89,90 https://amazon.com.br/x')
        self.assertTrue(parsed['menor_preco'])
        self.assertIn('menor_preco', parsed['labels'])

    def test_cupom_tipo_percentual(self):
        parsed = parse_observed_message('Cupom PROMO20 para 20% off https://amzn.to/x')
        self.assertEqual(parsed['cupom_tipo'], 'percentual')

    def test_cupom_tipo_frete_gratis(self):
        parsed = parse_observed_message('Cupom FRETAO com frete grátis https://mercadolivre.com.br/x')
        self.assertEqual(parsed['cupom_tipo'], 'frete_gratis')
        self.assertIn('frete_gratis', parsed['labels'])

    def test_desconto_labels(self):
        parsed = parse_observed_message('De R$ 1000 por R$ 499,90 https://mercadolivre.com.br/x')
        self.assertIn('desconto_50', parsed['labels'])
        self.assertIn('desconto_30', parsed['labels'])
        self.assertNotIn('desconto_70', parsed['labels'])

    def test_desconto_70_label(self):
        parsed = parse_observed_message('De R$ 1000 por R$ 299,90 https://mercadolivre.com.br/x')
        self.assertIn('desconto_70', parsed['labels'])

    def test_no_prices_yields_empty_fields(self):
        parsed = parse_observed_message('Confira essa oferta')
        self.assertEqual(parsed['price'], '')
        self.assertIsNone(parsed['parcelamento'])
        self.assertFalse(parsed['pix'] or False)
        self.assertEqual(parsed['cupom_tipo'], '')


class MarketIntelParserV2CopyTests(TestCase):
    """P0-3: Copy and format pattern extraction tests."""

    def test_emoji_density(self):
        parsed = parse_observed_message('🔥🔥🔥 Promoção incrível! Confira já!')
        self.assertIsNotNone(parsed['emoji_densidade'])
        self.assertGreater(parsed['emoji_densidade'], 0)

    def test_emojis_top(self):
        parsed = parse_observed_message('🔥🔥 Promo 🛒 Confira!')
        self.assertIn('🔥', parsed['emojis_top'])
        self.assertIn('🛒', parsed['emojis_top'])

    def test_no_emoji_yields_empty(self):
        parsed = parse_observed_message('Texto sem emoji')
        self.assertEqual(parsed['emojis_top'], [])

    def test_headline_detection_emoji(self):
        parsed = parse_observed_message('🔥 OFERTA IMPERDÍVEL\nConfira!')
        self.assertTrue(parsed['tem_headline'])

    def test_headline_detection_uppercase(self):
        parsed = parse_observed_message('OFERTA DO DIA\nMuito bom')
        self.assertTrue(parsed['tem_headline'])

    def test_no_headline(self):
        parsed = parse_observed_message('confira essa oferta')
        self.assertFalse(parsed['tem_headline'])

    def test_cta_detection_corre(self):
        parsed = parse_observed_message('Corre que está acabando!')
        self.assertTrue(parsed['tem_cta'])
        self.assertIn('corre', parsed['cta_termos'])

    def test_usa_caixa_alta(self):
        parsed = parse_observed_message('OFERTA IMPERDÍVEL COMPRE AGORA')
        self.assertTrue(parsed['usa_caixa_alta'])

    def test_usa_negrito_markdown(self):
        parsed = parse_observed_message('Confira *oferta incrível* no site!')
        self.assertTrue(parsed['usa_negrito'])

    def test_tipo_midia_foto(self):
        parsed = parse_observed_message('Oferta com imagem', has_image=True)
        self.assertEqual(parsed['tipo_midia'], 'foto_oficial')

    def test_tipo_midia_texto(self):
        parsed = parse_observed_message('Oferta texto simples', has_image=False)
        self.assertEqual(parsed['tipo_midia'], 'texto')

    def test_tamanho_mensagem(self):
        text = 'Um texto médio para medir tamanho'
        parsed = parse_observed_message(text)
        self.assertEqual(parsed['tamanho_mensagem'], len(text))


class MarketIntelParserV2MarketplaceTests(TestCase):
    """P1-5: Marketplace detection enrichment tests."""

    def test_shein_detected(self):
        parsed = parse_observed_message('Vestido Shein R$ 79,90 https://shein.com.br/x')
        self.assertEqual(parsed['marketplace'], 'shein')

    def test_americanas_detected(self):
        parsed = parse_observed_message('Notebook R$ 2999 https://americanas.com.br/x')
        self.assertEqual(parsed['marketplace'], 'americanas')

    def test_kabum_detected(self):
        parsed = parse_observed_message('SSD 1TB R$ 499,90 https://kabum.com.br/x')
        self.assertEqual(parsed['marketplace'], 'kabum')

    def test_casas_bahia_detected(self):
        parsed = parse_observed_message('Geladeira R$ 1899 https://casasbahia.com.br/x')
        self.assertEqual(parsed['marketplace'], 'casas_bahia')

    def test_unknown_domain_recorded(self):
        parsed = parse_observed_message('Oferta R$ 99 https://www.lojaDesconhecida.com.br/x')
        self.assertEqual(parsed['marketplace'], 'desconhecido')
        self.assertNotEqual(parsed['marketplace_dominio_desconhecido'], '')

    def test_known_domain_no_unknown_recorded(self):
        parsed = parse_observed_message('Oferta R$ 99 https://amzn.to/x')
        self.assertEqual(parsed['marketplace'], 'amazon')
        self.assertEqual(parsed['marketplace_dominio_desconhecido'], '')

    def test_programa_entrega_prime(self):
        parsed = parse_observed_message('Entrega Prime grátis R$ 199 https://amzn.to/x')
        self.assertEqual(parsed['programa_entrega'], 'prime')

    def test_programa_entrega_full(self):
        parsed = parse_observed_message('Entrega Full R$ 299 https://mercadolivre.com.br/x')
        self.assertEqual(parsed['programa_entrega'], 'full')

    def test_programa_entrega_frete_gratis(self):
        parsed = parse_observed_message('Frete grátis acima de R$ 79 https://shopee.com.br/x')
        self.assertEqual(parsed['programa_entrega'], 'frete_gratis')


class MarketIntelParserV2BrandTests(TestCase):
    """P1-6: Brand extraction tests."""

    def test_nike_in_text(self):
        parsed = parse_observed_message('Tênis Nike Air Max R$ 599,90 https://amzn.to/x')
        self.assertEqual(parsed['marca'], 'nike')

    def test_samsung_in_text(self):
        parsed = parse_observed_message('Monitor Samsung 27" R$ 1299 https://amzn.to/x')
        self.assertEqual(parsed['marca'], 'samsung')

    def test_no_brand(self):
        parsed = parse_observed_message('Oferta genérica R$ 49,90')
        self.assertEqual(parsed['marca'], '')


class MarketIntelReportV1Tests(TestCase):
    """Regression tests: v1 report output remains unchanged."""

    def test_generate_daily_report_aggregates_without_exposing_sender_or_raw_urls(self):
        group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas A https://grupo.example 120363000000000001@g.us 5521983554018-1540851269@g.us 5511999999999:12@s.whatsapp.net',
            jid='120363000000000001@g.us',
            is_enabled=True,
        )
        sent_at = timezone.now() - timedelta(hours=1)
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='MSG1',
            sender_hash='a' * 64,
            sent_at=sent_at,
            collected_at=sent_at,
            text='Corre! Air Fryer por R$ 199,90 com cupom CASA10 https://amzn.to/oferta',
            urls=['https://amzn.to/oferta'],
            has_image=True,
            raw_type='imageMessage',
            parsed_marketplace='amazon',
            parsed_price=Decimal('199.90'),
            parsed_coupon='CASA10',
            editorial_labels=['urgencia', 'cupom', 'ate_300', 'imagem'],
            scraper_hints=['termo:air fryer', 'categoria:casa/cozinha'],
        )

        report = generate_daily_report(date.today())
        payload = build_daily_report_payload(report)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(report.messages_analyzed, 1)
        self.assertEqual(payload['cycle_summary']['top_marketplaces'][0]['marketplace'], 'amazon')
        self.assertEqual(payload['summary']['messages_analyzed'], 1)
        self.assertEqual(payload['analyzed_offers'][0]['marketplace'], 'amazon')
        self.assertNotIn('"sender_hash"', serialized)
        self.assertNotIn('"message_id"', serialized)
        self.assertNotIn('120363000000000001@g.us', serialized)
        self.assertNotIn('5521983554018-1540851269@g.us', serialized)
        self.assertNotIn('5511999999999:12@s.whatsapp.net', serialized)
        self.assertNotIn('https://amzn.to/oferta', serialized)
        self.assertIn('termo:air fryer', serialized)

    def test_payload_is_incremental_and_includes_previous_analyzed_offers_without_private_fields(self):
        group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas A https://grupo.example 120363000000000001@g.us 5521983554018-1540851269@g.us 5511999999999:12@s.whatsapp.net',
            jid='120363000000000001@g.us',
            is_enabled=True,
        )
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='OLD1',
            sender_hash='b' * 64,
            sent_at=yesterday,
            collected_at=yesterday,
            text='Oferta antiga com link https://amzn.to/antiga',
            urls=['https://amzn.to/antiga'],
            has_image=False,
            raw_type='conversation',
            parsed_marketplace='amazon',
            parsed_price=Decimal('99.90'),
            parsed_coupon='',
            editorial_labels=['ate_100'],
            scraper_hints=['faixa_preco:ate_100'],
        )
        ObservedWhatsAppMessage.objects.create(
            group=group,
            external_message_id='NEW1',
            sender_hash='c' * 64,
            sent_at=now,
            collected_at=now,
            text='Oferta nova com link https://mercadolivre.com.br/nova',
            urls=['https://mercadolivre.com.br/nova'],
            has_image=True,
            raw_type='imageMessage',
            parsed_marketplace='mercadolivre',
            parsed_price=Decimal('149.90'),
            parsed_coupon='NOVO10',
            editorial_labels=['cupom', 'imagem', 'ate_300'],
            scraper_hints=['faixa_preco:ate_300'],
        )

        report = generate_daily_report(date.today())
        report.summary_json = {'top_groups': [{'group': '120363000000000001@g.us https://leak.example', 'count': 99}]}
        report.recommendations_json = [{'title': 'Oferta antiga https://leak.example'}]
        report.scraper_opportunities_json = [{'hint': 'https://leak.example', 'count': 99}]
        report.save(update_fields=['summary_json', 'recommendations_json', 'scraper_opportunities_json', 'updated_at'])
        payload = build_daily_report_payload(report)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(report.messages_analyzed, 1)
        self.assertEqual(payload['cycle_summary']['messages_analyzed'], 1)
        self.assertEqual(payload['summary']['messages_analyzed'], 2)
        self.assertEqual(len(payload['analyzed_offers']), 2)
        self.assertEqual(
            [offer['marketplace'] for offer in payload['analyzed_offers']],
            ['mercadolivre', 'amazon'],
        )
        self.assertNotIn('"sender_hash"', serialized)
        self.assertNotIn('"message_id"', serialized)
        self.assertNotIn('OLD1', serialized)
        self.assertNotIn('NEW1', serialized)
        self.assertNotIn('120363000000000001@g.us', serialized)
        self.assertNotIn('5521983554018-1540851269@g.us', serialized)
        self.assertNotIn('5511999999999:12@s.whatsapp.net', serialized)
        self.assertNotIn('https://amzn.to/antiga', serialized)
        self.assertNotIn('https://mercadolivre.com.br/nova', serialized)


class MarketIntelReportV2Tests(TestCase):
    """Tests for v2 report blocks."""

    def setUp(self):
        self.group = ObservedWhatsAppGroup.objects.create(
            name='Ofertas Teste',
            jid='120363000000000001@g.us',
            is_enabled=True,
        )
        self.sent_at = timezone.now() - timedelta(hours=1)

    def _create_message(self, **kwargs):
        defaults = {
            'group': self.group,
            'external_message_id': f'MSG-{kwargs.get("external_message_id", id(kwargs))}',
            'sender_hash': 'a' * 64,
            'sent_at': self.sent_at,
            'collected_at': self.sent_at,
            'text': 'Oferta de teste',
            'urls': [],
            'has_image': False,
            'raw_type': 'conversation',
            'parsed_marketplace': 'mercadolivre',
            'parsed_price': Decimal('199.90'),
            'parsed_original_price': Decimal('399.90'),
            'parsed_discount_pct': Decimal('50.01'),
            'parsed_coupon': 'PROMO50',
            'editorial_labels': ['cupom', 'ate_300', 'desconto_50', 'pix', 'parcelado_sem_juros'],
            'scraper_hints': ['categoria:moda', 'faixa_preco:ate_300', 'desconto:desconto_50'],
            'parcelamento': 10,
            'parcelado_sem_juros': True,
            'pix': True,
            'cashback': False,
            'menor_preco': False,
            'cupom_tipo': 'percentual',
            'marca': 'nike',
            'tipo_midia': 'foto_oficial',
            'tamanho_mensagem': 250,
            'tem_headline': True,
            'tem_cta': True,
            'cta_termos': ['corre'],
            'usa_caixa_alta': True,
            'usa_negrito': False,
            'emoji_densidade': Decimal('0.15'),
            'emojis_top': ['🔥'],
        }
        defaults.update(kwargs)
        return ObservedWhatsAppMessage.objects.create(**defaults)

    def _create_offer(self, **kwargs):
        marketplace, _ = Marketplace.objects.get_or_create(
            code=kwargs.pop('marketplace_code', 'mercadolivre'),
            defaults={'name': 'Mercado Livre', 'base_url': 'https://www.mercadolivre.com.br'},
        )
        category, _ = Category.objects.get_or_create(
            code=kwargs.pop('category_code', 'moda'),
            defaults={'name': 'Moda'},
        )
        now = timezone.now()
        title = kwargs.get('title', 'Tênis Nike Air Max')
        defaults = {
            'marketplace': marketplace,
            'category': category,
            'external_id': kwargs.pop('external_id', 'OWN1'),
            'title': title,
            'normalized_title': kwargs.pop('normalized_title', title.lower()),
            'offer_hash': kwargs.pop('offer_hash', f'hash-{id(kwargs)}'),
            'current_price': kwargs.pop('current_price', Decimal('199.90')),
            'product_url': kwargs.pop('product_url', 'https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123'),
            'first_seen_at': kwargs.pop('first_seen_at', now),
            'last_seen_at': kwargs.pop('last_seen_at', now),
            'is_active': kwargs.pop('is_active', True),
        }
        defaults.update(kwargs)
        return Offer.objects.create(**defaults)

    def test_mecanica_preco_block(self):
        self._create_message(external_message_id='MEC1')
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_mecanica_preco(msgs)
        self.assertIn('desconto_50', result)
        self.assertGreaterEqual(result['desconto_50'], 1)
        self.assertIn('pix', result)
        self.assertGreaterEqual(result['pix'], 1)
        self.assertIn('parcelado_sem_juros', result)
        self.assertGreaterEqual(result['parcelado_sem_juros'], 1)
        self.assertIn('percentual', result['cupom_por_tipo'])
        self.assertIn('por_marketplace', result)

    def test_copy_e_formato_block(self):
        self._create_message(external_message_id='COPY1')
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_copy_e_formato(msgs)
        self.assertIn('emoji_densidade_media', result)
        self.assertIn('emojis_top', result)
        self.assertIn('tem_headline_pct', result)
        self.assertIn('tem_cta_pct', result)
        self.assertIn('tipo_midia', result)
        self.assertIn('tamanho_mensagem_media', result)

    def test_marcas_por_categoria(self):
        self._create_message(external_message_id='BRAND1')
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_marcas_por_categoria(msgs)
        # Should have 'moda' category with 'nike' brand
        self.assertIn('moda', result)
        found_nike = any(m['marca'] == 'nike' for m in result['moda'])
        self.assertTrue(found_nike)

    def test_marketplace_detalhado(self):
        self._create_message(
            external_message_id='MKT1',
            parsed_marketplace='desconhecido',
            marketplace_dominio_desconhecido='lojaDesconhecida.com.br',
        )
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_marketplace_detalhado(msgs)
        self.assertIn('contagem', result)
        self.assertIn('dominios_desconhecidos', result)
        self.assertIn('lojaDesconhecida.com.br', result['dominios_desconhecidos'])

    def test_sinais_engajamento_without_data(self):
        self._create_message(external_message_id='ENG1')
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_sinais_engajamento(msgs)
        # Without engagement data, should return note
        self.assertIn('nota', result)
        self.assertTrue(len(result['nota']) > 0)
        self.assertEqual(result['top_por_engajamento'], [])

    def test_sinais_engajamento_with_partial_data_scores_and_averages(self):
        self._create_message(
            external_message_id='ENG2',
            reacoes=40,
            visualizacoes=1000,
            encaminhamentos=5,
            comentarios=None,
            repostado=True,
            qtd_repostagens=2,
            fixado=True,
        )
        self._create_message(
            external_message_id='ENG3',
            sender_hash='e' * 64,
            parsed_marketplace='amazon',
            reacoes=None,
            visualizacoes=500,
            encaminhamentos=None,
            comentarios=None,
        )
        result = build_sinais_engajamento(ObservedWhatsAppMessage.objects.all())
        self.assertEqual(result['nota'], '')
        self.assertEqual(result['top_por_engajamento'][0]['marketplace'], 'mercadolivre')
        self.assertIn('mercadolivre', result['engajamento_medio_por_marketplace'])
        self.assertIn('moda', result['engajamento_medio_por_categoria'])

    def test_cadencia_e_timing_block(self):
        self._create_message(external_message_id='TIME1')
        self._create_message(
            external_message_id='TIME2',
            sender_hash='b' * 64,
            sent_at=self.sent_at + timedelta(hours=3),
            collected_at=self.sent_at + timedelta(hours=3),
        )
        msgs = ObservedWhatsAppMessage.objects.all()
        result = build_cadencia_e_timing(msgs)
        self.assertIn('heatmap_horario_dia', result)
        self.assertIn('frequencia_por_grupo', result)
        self.assertIn('intervalo_medio_por_grupo', result)
        self.assertIn('lag_cobertura', result)
        self.assertIn('sazonalidade', result)

    def test_cadencia_e_timing_lag_cobertura(self):
        self._create_offer(
            product_url='https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123',
            first_seen_at=self.sent_at + timedelta(hours=2),
        )
        self._create_message(
            external_message_id='TIME-LAG',
            text='Tênis Nike Air Max R$ 199,90 https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123?utm=abc',
            urls=['https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123?utm=abc'],
        )
        result = build_cadencia_e_timing(ObservedWhatsAppMessage.objects.all())
        self.assertEqual(result['lag_cobertura']['amostras'], 1)
        self.assertEqual(result['lag_cobertura']['concorrente_publicou_primeiro'], 1)
        self.assertEqual(result['lag_cobertura']['lag_medio_horas'], 2.0)

    def test_cadencia_e_timing_detects_accented_sazonalidade(self):
        self._create_message(
            external_message_id='TIME-MAES',
            text='Especial Dia das Mães com ofertas de beleza',
        )
        result = build_cadencia_e_timing(ObservedWhatsAppMessage.objects.all())
        self.assertIn({'evento': 'dia_das_maes', 'count': 1}, result['sazonalidade'])

    def test_cobertura_matches_by_normalized_url_and_title_without_leaking_urls(self):
        self._create_offer(
            product_url='https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123',
            normalized_title='tenis nike air max',
            first_seen_at=self.sent_at - timedelta(hours=1),
        )
        self._create_message(
            external_message_id='COV-URL',
            text='Tênis Nike Air Max por R$ 199,90 https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123?utm=concorrente',
            urls=['https://www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123?utm=concorrente'],
        )
        self._create_message(
            external_message_id='COV-TITLE',
            sender_hash='f' * 64,
            text='Corre! TENIS NIKE AIR MAX caiu de preço',
            urls=[],
        )
        self._create_message(
            external_message_id='COV-GAP',
            sender_hash='g' * 64,
            parsed_marketplace='shopee',
            text='Oferta exclusiva concorrente R$ 88 https://shopee.com.br/outro',
            urls=['https://shopee.com.br/outro'],
        )
        result = build_cobertura(ObservedWhatsAppMessage.objects.all())
        self.assertEqual(result['taxa_sobreposicao'], 0.67)
        self.assertEqual(result['exclusivas_concorrente'], 1)
        self.assertEqual(result['metodo_match']['url'], 1)
        self.assertEqual(result['metodo_match']['titulo_normalizado'], 1)
        self.assertEqual(result['backlog_curadoria'][0]['comb'], 'shopee:moda')
        self.assertNotIn('https://shopee.com.br/outro', json.dumps(result))

    def test_cobertura_matches_scheme_less_urls(self):
        self._create_offer(
            product_url='www.mercadolivre.com.br/tenis-nike-air-max/p/MLB123',
            normalized_title='tenis nike air max',
        )
        self._create_message(
            external_message_id='COV-SCHEMELESS',
            text='Tênis Nike Air Max por R$ 199,90 mercadolivre.com.br/tenis-nike-air-max/p/MLB123',
            urls=['mercadolivre.com.br/tenis-nike-air-max/p/MLB123'],
        )
        result = build_cobertura(ObservedWhatsAppMessage.objects.all())
        self.assertEqual(result['taxa_sobreposicao'], 1.0)
        self.assertEqual(result['metodo_match']['url'], 1)

    def test_v2_payload_includes_new_blocks(self):
        self._create_message(external_message_id='V2FULL')
        report = generate_daily_report(date.today())
        payload = build_daily_report_payload(report)
        self.assertEqual(payload['version'], '2.0')
        self.assertIn('mecanica_preco', payload)
        self.assertIn('mecanica_preco_acumulada', payload)
        self.assertIn('copy_e_formato', payload)
        self.assertIn('copy_e_formato_acumulada', payload)
        self.assertIn('sinais_engajamento', payload)
        self.assertIn('sinais_engajamento_acumulado', payload)
        self.assertIn('marketplace_detalhado', payload)
        self.assertIn('marketplace_detalhado_acumulado', payload)
        self.assertIn('marcas_por_categoria', payload)
        self.assertIn('marcas_por_categoria_acumulada', payload)
        self.assertIn('cadencia_e_timing', payload)
        self.assertIn('cadencia_e_timing_acumulada', payload)
        self.assertIn('cobertura', payload)
        self.assertIn('cobertura_acumulada', payload)
        self.assertIn('insights_inteligentes', payload)
        self.assertEqual(payload['insights_inteligentes']['status'], 'ok')

    def test_intelligent_insights_turns_counts_into_actions(self):
        self._create_message(
            external_message_id='INSIGHT1',
            parsed_marketplace='desconhecido',
            editorial_labels=['cupom', 'imagem', 'pix'],
            has_image=True,
            parsed_coupon='PROMO10',
            urls=['https://lojaexemplo.com/oferta'],
        )
        report = generate_daily_report(date.today())
        result = build_intelligent_insights(report, ObservedWhatsAppMessage.objects.all())
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result['status'], 'ok')
        self.assertIn('resumo_executivo', result)
        self.assertTrue(result['oportunidades_prioritarias'])
        self.assertTrue(result['acoes_recomendadas'])
        self.assertNotIn('https://lojaexemplo.com/oferta', serialized)

    def test_intelligent_insights_alerts_when_cycle_has_no_data(self):
        report = generate_daily_report(date.today())
        result = build_intelligent_insights(report, ObservedWhatsAppMessage.objects.none())

        self.assertEqual(result['status'], 'sem_dados')
        self.assertEqual(result['alertas'][0]['severidade'], 'critico')
        self.assertTrue(result['acoes_recomendadas'])

    def test_v1_blocks_unchanged(self):
        """Ensure v1 blocks (summary, recommendations, scraper_opportunities) are intact."""
        self._create_message(external_message_id='V1REG')
        report = generate_daily_report(date.today())
        payload = build_daily_report_payload(report)
        # v1 block keys must still be present
        self.assertIn('summary', payload)
        self.assertIn('cycle_summary', payload)
        self.assertIn('recommendations', payload)
        self.assertIn('cycle_recommendations', payload)
        self.assertIn('scraper_opportunities', payload)
        self.assertIn('cycle_scraper_opportunities', payload)
        self.assertIn('analyzed_offers', payload)
        # summary must still have the same structure
        self.assertIn('top_marketplaces', payload['summary'])
        self.assertIn('top_labels', payload['summary'])
        self.assertIn('top_groups', payload['summary'])
        self.assertIn('messages_analyzed', payload['summary'])

    def test_degradation_graceful_null_values(self):
        """All null fields should not distort aggregates."""
        ObservedWhatsAppMessage.objects.create(
            group=self.group,
            external_message_id='NULLTEST',
            sender_hash='n' * 64,
            sent_at=self.sent_at,
            collected_at=self.sent_at,
            text='Texto sem preços nem imagens',
            urls=[],
            has_image=False,
            raw_type='conversation',
            parsed_marketplace='',
            parsed_price=None,
            parsed_original_price=None,
            parsed_discount_pct=None,
            parsed_coupon='',
            editorial_labels=[],
            scraper_hints=[],
            # All v2 fields left as defaults (null/empty)
        )
        msgs = ObservedWhatsAppMessage.objects.all()
        # Should not crash
        mecanica = build_mecanica_preco(msgs)
        self.assertEqual(mecanica['desconto_30'], 0)
        self.assertEqual(mecanica['pix'], 0)

        copy = build_copy_e_formato(msgs)
        self.assertEqual(copy['emoji_densidade_media'], 0)
        self.assertEqual(copy['tamanho_mensagem_media'], 0)

        marcas = build_marcas_por_categoria(msgs)
        # Empty message with no category or brand
        self.assertEqual(len(marcas), 0)

        mktdetalhado = build_marketplace_detalhado(msgs)
        self.assertIn('desconhecido', mktdetalhado['contagem'])