"""Testes do parser de conversão Shopee (Sprint 4 - Tarefa 4.1).

Cobre a mudança principal da tarefa: reconstruir `AffiliateConversion.social_channel`
a partir da coluna `Sub Id 2` (formato curto `wa_<canal>`/`tg_<canal>`, mesma
convenção de `_short_channel_code()` em `apps/analytics/services/link_builder.py`).
"""

from django.test import TestCase

from apps.analytics.models import AffiliateConversion, AffiliateSource
from apps.analytics.services.affiliate_parsers.shopee import (
    _resolve_social_channel_from_subid,
    parse_shopee_report,
)
from apps.distribution.models import SocialChannel


class ResolveSocialChannelFromSubidTests(TestCase):
    """Testa `_resolve_social_channel_from_subid` isoladamente (unidade)."""

    def setUp(self):
        self.wa_principal = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )
        self.tg_homolog = SocialChannel.objects.create(
            name='Telegram Homolog',
            code='telegram_homolog',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='@homolog',
        )

    def test_resolves_whatsapp_prefix(self):
        self.assertEqual(
            _resolve_social_channel_from_subid('wa_principal'),
            self.wa_principal,
        )

    def test_resolves_telegram_prefix_case_insensitive(self):
        self.assertEqual(
            _resolve_social_channel_from_subid('TG_HOMOLOG'),
            self.tg_homolog,
        )

    def test_empty_subid_returns_none(self):
        self.assertIsNone(_resolve_social_channel_from_subid(''))
        self.assertIsNone(_resolve_social_channel_from_subid(None))

    def test_unknown_prefix_returns_none(self):
        # Instagram/site não são SocialChannel neste catálogo — degradação aceitável.
        self.assertIsNone(_resolve_social_channel_from_subid('ig_story'))
        self.assertIsNone(_resolve_social_channel_from_subid('site'))

    def test_known_prefix_without_matching_channel_returns_none(self):
        self.assertIsNone(_resolve_social_channel_from_subid('wa_canal_inexistente'))

    def test_prefix_without_rest_returns_none(self):
        self.assertIsNone(_resolve_social_channel_from_subid('wa_'))
        self.assertIsNone(_resolve_social_channel_from_subid('wa'))


class ParseShopeeReportSubidChannelTests(TestCase):
    """Testa o fluxo completo de `parse_shopee_report` persistindo social_channel."""

    def setUp(self):
        self.wa_principal = SocialChannel.objects.create(
            name='WhatsApp Principal',
            code='whatsapp_principal',
            channel_type=SocialChannel.ChannelType.WHATSAPP_GROUP,
            target='Grupo Principal',
        )
        self.tg_homolog = SocialChannel.objects.create(
            name='Telegram Homolog',
            code='telegram_homolog',
            channel_type=SocialChannel.ChannelType.TELEGRAM_CHANNEL,
            target='@homolog',
        )

    def _build_payload(self) -> bytes:
        rows = [
            'Item ID,Shop ID,Item Name,Conversion Time,Status,Sub Id 2,Quantity,Commission',
            # resolve -> whatsapp_principal
            '111,1,Produto A,2026-07-13,confirmed,wa_principal,1,10.50',
            # resolve -> telegram_homolog
            '222,1,Produto B,2026-07-14,confirmed,tg_homolog,1,5.25',
            # prefixo desconhecido (instagram) -> não resolve
            '333,1,Produto C,2026-07-15,confirmed,ig_story,1,3.00',
            # sem subId2 -> não entra na contagem de resolvido/não-resolvido
            '444,1,Produto D,2026-07-16,confirmed,,1,2.00',
            # prefixo conhecido mas sem SocialChannel correspondente -> não resolve
            '555,1,Produto E,2026-07-17,confirmed,wa_canal_inexistente,1,1.00',
        ]
        return ('\n'.join(rows)).encode('utf-8')

    def test_social_channel_resolved_from_subid2_when_recognized(self):
        result = parse_shopee_report(self._build_payload(), filename='conversao.csv')

        self.assertEqual(result.imported, 5)

        conv_a = AffiliateConversion.objects.get(external_ref='111:1', source=AffiliateSource.SHOPEE)
        self.assertEqual(conv_a.social_channel, self.wa_principal)

        conv_b = AffiliateConversion.objects.get(external_ref='222:1', source=AffiliateSource.SHOPEE)
        self.assertEqual(conv_b.social_channel, self.tg_homolog)

    def test_social_channel_stays_null_when_subid_unrecognized_or_absent(self):
        parse_shopee_report(self._build_payload(), filename='conversao.csv')

        conv_c = AffiliateConversion.objects.get(external_ref='333:1', source=AffiliateSource.SHOPEE)
        self.assertIsNone(conv_c.social_channel)

        conv_d = AffiliateConversion.objects.get(external_ref='444:1', source=AffiliateSource.SHOPEE)
        self.assertIsNone(conv_d.social_channel)

        conv_e = AffiliateConversion.objects.get(external_ref='555:1', source=AffiliateSource.SHOPEE)
        self.assertIsNone(conv_e.social_channel)

    def test_batch_warnings_report_resolved_vs_unresolved_channel_counts(self):
        result = parse_shopee_report(self._build_payload(), filename='conversao.csv')

        channel_warning = next(
            (w for w in result.warnings if 'SubID de canal' in w), None,
        )
        self.assertIsNotNone(channel_warning, result.warnings)
        self.assertIn('2 item(ns) resolveram social_channel', channel_warning)
        self.assertIn('2 não resolveram', channel_warning)
