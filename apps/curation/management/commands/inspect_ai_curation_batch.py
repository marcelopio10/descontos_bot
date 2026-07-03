from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.curation.models import CuratedBatch, CurationDecision, CurationRun
from apps.curation.services.selector import get_selection_config, select_offers_for_channel
from apps.distribution.models import SocialChannel

DEFAULT_CHANNEL_CODE = 'whatsapp_main'


class Command(BaseCommand):
    help = 'Inspeciona o último lote de curadoria IA de um canal, sem enviar nada.'

    def add_arguments(self, parser):
        parser.add_argument('--channel', default=DEFAULT_CHANNEL_CODE, help='Código do canal social.')
        parser.add_argument('--run-id', type=int, default=None, help='ID específico de CurationRun.')
        parser.add_argument('--compare-selector', action='store_true', help='Compara lote IA com selector determinístico atual.')

    def handle(self, *args, **options):
        channel = self._get_channel(options['channel'])
        run = self._get_run(channel=channel, run_id=options['run_id'])
        batch = getattr(run, 'batch', None)

        self.stdout.write(f'Run #{run.id}: status={run.status} mode={run.mode} channel={channel.code}')
        self.stdout.write(f'Candidatas: {run.candidate_count}; selecionadas: {run.selected_count}')
        self.stdout.write(f'Distribuição: {run.actual_distribution_json or {}}')
        if run.public_json_path:
            self.stdout.write(f'JSON público: {run.public_json_path}')
        if run.error_message:
            self.stdout.write(f'Erro: {run.error_message}')

        if batch:
            self.stdout.write(f'Batch #{batch.id}: status={batch.status} size={batch.batch_size}')
            self.stdout.write('Itens:')
            for item in batch.items.select_related('offer', 'decision').order_by('position'):
                self.stdout.write(
                    f'  #{item.position} offer={item.offer_id} marketplace={item.decision.marketplace_code} '
                    f'class={item.decision.ai_classification} title={item.final_title[:80]}'
                )
        else:
            self.stdout.write('Batch: inexistente')

        if options['compare_selector']:
            self._write_selector_comparison(channel=channel, run=run, batch=batch)

        total_decisions = run.decisions.count()
        rejected = run.decisions.exclude(ai_classification=CurationDecision.Classification.APPROVED).count()
        not_selected = run.decisions.filter(is_selected_for_batch=False).count()
        self.stdout.write('Decisões:')
        self.stdout.write(f'  total={total_decisions}; não selecionadas={not_selected}')
        self.stdout.write('Rejeições:')
        self.stdout.write(f'  rejected_or_improper={rejected}')

    def _write_selector_comparison(self, *, channel: SocialChannel, run: CurationRun, batch: CuratedBatch | None) -> None:
        config = get_selection_config()
        deterministic = select_offers_for_channel(channel, config)
        deterministic_ids = [offer.id for offer in deterministic]
        ai_ids = [item.offer_id for item in batch.items.order_by('position')] if batch else []
        overlap = [offer_id for offer_id in ai_ids if offer_id in deterministic_ids]
        ai_only = [offer_id for offer_id in ai_ids if offer_id not in deterministic_ids]
        selector_only = [offer_id for offer_id in deterministic_ids if offer_id not in ai_ids]
        self.stdout.write('Comparação selector atual vs agente:')
        self.stdout.write(f'  selector_count={len(deterministic_ids)}; ai_count={len(ai_ids)}; overlap={len(overlap)}')
        self.stdout.write(f'  ai_only={ai_only[:10]}')
        self.stdout.write(f'  selector_only={selector_only[:10]}')

    def _get_channel(self, code: str) -> SocialChannel:
        try:
            return SocialChannel.objects.get(code=code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(f'Canal não encontrado: {code}') from exc

    def _get_run(self, *, channel: SocialChannel, run_id: int | None) -> CurationRun:
        queryset = CurationRun.objects.filter(channel=channel)
        if run_id is not None:
            queryset = queryset.filter(id=run_id)
        run = queryset.order_by('-created_at').first()
        if run is None:
            raise CommandError(f'Nenhum run de curadoria encontrado para channel={channel.code}.')
        return run
