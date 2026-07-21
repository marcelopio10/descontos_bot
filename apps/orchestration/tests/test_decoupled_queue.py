"""Sprint 3 - Tarefa 3.3: flag `usa_fila_desacoplada`.

Com a flag desligada (default), `run_bot` continua preparando e consumindo o
lote de curadoria IA no mesmo ciclo (comportamento coberto por
`test_run_bot_ai_curation.py`, que não é tocado aqui). Com a flag ligada,
`run_bot` deve só preparar o lote e parar; o consumo passa a ser
responsabilidade do comando novo `consumir_fila_whatsapp`.
"""
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.curation.models import CuratedBatch, CuratedBatchItem, CurationDecision, CurationRun
from apps.curation.services.settings import get_bool_setting
from apps.distribution.models import Delivery, SocialChannel
from apps.marketplaces.models import Marketplace
from apps.offers.models import Offer
from apps.panel.models import Setting


class DecoupledQueueFlagTestsMixin:
    """Cria canal/marketplace/oferta/lote pronto, reaproveitado pelos dois testes."""

    def _make_channel(self, *, code: str, target: str) -> SocialChannel:
        return SocialChannel.objects.create(
            name=f'Canal {code}',
            code=code,
            target=target,
            link_strategy=SocialChannel.LinkStrategy.BRIDGE_ONLY,
        )

    def _make_offer(self, marketplace: Marketplace, suffix: str) -> Offer:
        now = timezone.now()
        return Offer.objects.create(
            marketplace=marketplace,
            external_id=f'ml-{suffix}',
            title=f'Título oferta {suffix}',
            normalized_title=f'titulo oferta {suffix}',
            offer_hash=f'hash-{suffix}',
            slug=f'titulo-oferta-{suffix}',
            current_price=Decimal('99.90'),
            original_price=Decimal('199.80'),
            discount_pct=Decimal('50.00'),
            product_url='https://example.com/produto',
            affiliate_url='https://example.com/afiliado',
            image_url='https://example.com/img.jpg',
            is_active=True,
            first_seen_at=now,
            last_seen_at=now,
            price_collected_at=now,
        )

    def _create_ready_batch(
        self,
        channel: SocialChannel,
        offer: Offer,
        mode: str = CurationRun.Mode.DRY_RUN,
    ) -> CuratedBatch:
        run = CurationRun.objects.create(
            channel=channel,
            status=CurationRun.Status.COMPLETED,
            mode=mode,
            profile_name='descontos-bot',
            model_provider='openai-codex',
            model_name='gpt-5.5',
            candidate_count=1,
            selected_count=1,
        )
        decision = CurationDecision.objects.create(
            run=run,
            offer=offer,
            marketplace_code=offer.marketplace.code,
            ai_score=Decimal('90'),
            ai_classification=CurationDecision.Classification.APPROVED,
            conversion_score=Decimal('90'),
            relevance_score=Decimal('90'),
            discount_quality_score=Decimal('90'),
            audience_fit_score=Decimal('90'),
            decision_reason='Boa oferta curada.',
            title_original=offer.title,
            title_rewritten='Título curado pela IA',
            caption_rewritten='Caption WhatsApp curada pela IA',
            raw_ai_json={},
            is_selected_for_batch=True,
        )
        batch = CuratedBatch.objects.create(
            run=run,
            channel=channel,
            status=CuratedBatch.Status.READY,
            batch_size=1,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        CuratedBatchItem.objects.create(
            batch=batch,
            decision=decision,
            offer=offer,
            position=1,
            final_title='Título curado pela IA',
            final_caption_whatsapp='Caption WhatsApp curada pela IA',
            final_caption_telegram='Caption Telegram curada pela IA',
            final_image_url='https://example.com/img-final.jpg',
        )
        return batch


class GetBoolSettingTests(TestCase):
    def test_default_is_returned_when_setting_missing(self):
        self.assertFalse(get_bool_setting('usa_fila_desacoplada', False))
        self.assertTrue(get_bool_setting('usa_fila_desacoplada', True))

    def test_truthy_values_parsed_case_insensitive_with_whitespace(self):
        for raw in ('1', 'true', 'True', ' TRUE ', 'yes', 'on', 'ON'):
            Setting.objects.update_or_create(key='usa_fila_desacoplada', defaults={'value': raw})
            self.assertTrue(get_bool_setting('usa_fila_desacoplada', False), msg=f'valor={raw!r}')

    def test_falsy_or_unrecognized_values_return_false(self):
        for raw in ('0', 'false', 'no', 'off', 'qualquer-coisa', ''):
            Setting.objects.update_or_create(key='usa_fila_desacoplada', defaults={'value': raw})
            self.assertFalse(get_bool_setting('usa_fila_desacoplada', True), msg=f'valor={raw!r}')


class RunBotDecoupledQueueFlagTests(DecoupledQueueFlagTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        # Canal de homologação (não é o alvo de produção 'descontos.bot'), para não
        # depender de ALLOW_PRODUCTION_WHATSAPP_SEND neste teste.
        self.channel = self._make_channel(code='whatsapp_homolog_flag', target='grupo-homolog-flag')
        self.offer = self._make_offer(self.marketplace, 'flag-1')

    def test_flag_off_default_keeps_prepare_and_consume_in_same_cycle(self):
        """Prova de rollback: sem Setting (default), o ciclo chama consumo como hoje."""
        batch = self._create_ready_batch(self.channel, self.offer)
        out = StringIO()

        with (
            patch('apps.orchestration.management.commands.run_bot.call_command'),
            patch(
                'apps.orchestration.management.commands.run_bot.Command._run_ai_curation_cycle',
                wraps=None,
            ) as consume,
        ):
            consume.return_value = True
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                self.channel.code,
                '--ai-curation',
                stdout=out,
            )

        consume.assert_called_once()
        self.assertNotIn('Fila desacoplada ativa', out.getvalue())
        batch.refresh_from_db()
        self.assertEqual(batch.status, CuratedBatch.Status.READY)

    def test_flag_on_prepares_but_does_not_consume(self):
        batch = self._create_ready_batch(self.channel, self.offer)
        Setting.objects.create(key='usa_fila_desacoplada', value='true')
        out = StringIO()

        with (
            patch('apps.orchestration.management.commands.run_bot.call_command') as prepare,
            patch(
                'apps.orchestration.management.commands.run_bot.Command._run_ai_curation_cycle',
            ) as consume,
        ):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                self.channel.code,
                '--ai-curation',
                stdout=out,
            )

        # Preparou o lote (mesma etapa de sempre)...
        prepare.assert_called_once()
        prepare_args = prepare.call_args.args
        self.assertEqual(prepare_args[:3], ('prepare_ai_curation_batch', '--channel', self.channel.code))
        # ...mas NÃO consumiu/enviou: fila desacoplada é responsabilidade de outro comando.
        consume.assert_not_called()

        text = out.getvalue()
        self.assertIn('Fila desacoplada ativa', text)
        self.assertIn('consumir_fila_whatsapp', text)

        batch.refresh_from_db()
        self.assertIsNone(batch.consumed_at)
        self.assertEqual(batch.status, CuratedBatch.Status.READY)
        self.assertEqual(Delivery.objects.count(), 0)
        # Item permanece pendente: quem consome é o comando separado.
        item = batch.items.get()
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.PENDING)

    def test_flag_on_without_ai_curation_is_ignored(self):
        """A flag só se aplica quando ai_curation está ativo (--legacy-selector ignora)."""
        Setting.objects.create(key='usa_fila_desacoplada', value='true')
        out = StringIO()

        call_command(
            'run_bot',
            '--dry-run',
            '--once',
            '--skip-scraping',
            '--channel',
            self.channel.code,
            '--legacy-selector',
            stdout=out,
        )

        self.assertNotIn('Fila desacoplada ativa', out.getvalue())


class ConsumirFilaWhatsappCommandTests(DecoupledQueueFlagTestsMixin, TestCase):
    def setUp(self):
        self.marketplace = Marketplace.objects.create(
            name='Mercado Livre',
            code='mercadolivre',
            base_url='https://mercadolivre.example.com',
            is_active=True,
        )
        self.channel = self._make_channel(code='whatsapp_homolog_consumo', target='grupo-homolog-consumo')
        self.offer = self._make_offer(self.marketplace, 'consumo-1')

    def test_dry_run_lists_items_without_delivering(self):
        batch = self._create_ready_batch(self.channel, self.offer)
        out = StringIO()

        with patch(
            'apps.orchestration.management.commands.consumir_fila_whatsapp.deliver_curated_item_to_whatsapp',
        ) as deliver_mock:
            call_command(
                'consumir_fila_whatsapp',
                '--dry-run',
                '--channel',
                self.channel.code,
                stdout=out,
            )

        deliver_mock.assert_not_called()
        text = out.getvalue()
        self.assertIn(f'Lote curado #{batch.id}', text)
        self.assertIn('Título curado pela IA', text)
        self.assertIn('dry_run ativo', text)
        self.assertEqual(Delivery.objects.count(), 0)
        batch.refresh_from_db()
        self.assertEqual(batch.status, CuratedBatch.Status.READY)

    def test_consumes_batch_prepared_by_run_bot_when_flag_on(self):
        """Fim-a-fim mockado: run_bot (flag on) prepara e para; consumir_fila_whatsapp
        (mockado, sem envio real) consegue consumir o lote que ficou pronto.
        """
        # mode=HOMOLOG porque o consumo (abaixo) roda sem --dry-run, e
        # consumir_fila_whatsapp só enxerga lotes HOMOLOG/PRODUCTION nesse caso
        # (mesma regra de allowed_modes que run_bot._run_ai_curation_cycle já usa).
        batch = self._create_ready_batch(self.channel, self.offer, mode=CurationRun.Mode.HOMOLOG)
        Setting.objects.create(key='usa_fila_desacoplada', value='true')
        prepare_out = StringIO()

        with (
            patch('apps.orchestration.management.commands.run_bot.call_command'),
            patch(
                'apps.orchestration.management.commands.run_bot.Command._run_ai_curation_cycle',
            ) as consume_in_run_bot,
        ):
            call_command(
                'run_bot',
                '--dry-run',
                '--once',
                '--skip-scraping',
                '--channel',
                self.channel.code,
                '--ai-curation',
                stdout=prepare_out,
            )
        consume_in_run_bot.assert_not_called()

        batch.refresh_from_db()
        self.assertEqual(batch.status, CuratedBatch.Status.READY)
        item = batch.items.get()
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.PENDING)

        def _fake_deliver(*, item, channel):
            item.send_status = CuratedBatchItem.SendStatus.SENT
            item.save(update_fields=['send_status'])
            delivery = SimpleNamespace(
                delivery_status='sent',
                id=999,
                external_message_id='wamid.fake',
                error_message='',
            )
            return SimpleNamespace(delivery=delivery, sent=True)

        consume_out = StringIO()
        with (
            patch(
                'apps.orchestration.management.commands.consumir_fila_whatsapp.get_whatsapp_session_status',
                return_value=SimpleNamespace(connected=True, jid='55119999@s.whatsapp.net'),
            ),
            patch(
                'apps.orchestration.management.commands.consumir_fila_whatsapp.deliver_curated_item_to_whatsapp',
                side_effect=_fake_deliver,
            ) as deliver_mock,
        ):
            call_command(
                'consumir_fila_whatsapp',
                '--channel',
                self.channel.code,
                stdout=consume_out,
            )

        deliver_mock.assert_called_once()
        text = consume_out.getvalue()
        self.assertIn(f'Lote curado #{batch.id}', text)
        self.assertIn('Enviadas 1/1 com curadoria IA.', text)
        item.refresh_from_db()
        self.assertEqual(item.send_status, CuratedBatchItem.SendStatus.SENT)

    def test_limit_argument_must_be_positive(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('consumir_fila_whatsapp', '--dry-run', '--limit', '0')

    def test_no_ready_batch_prints_reason_and_does_not_raise(self):
        out = StringIO()
        call_command('consumir_fila_whatsapp', '--dry-run', '--channel', self.channel.code, stdout=out)
        self.assertIn('Nenhum lote curado pronto', out.getvalue())
