from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.models import CurationRun
from apps.curation.services.ai_curator import prepare_ai_curation_batch
from apps.curation.services.image_processing import process_selected_batch_images
from apps.curation.services.selector import _eligible_offers, get_selection_config
from apps.distribution.models import SocialChannel

DEFAULT_CHANNEL_CODE = 'whatsapp_main'
DEFAULT_AUDIT_DIR = 'runtime/curation/ai_runs'
DEFAULT_PUBLIC_DIR = 'runtime/curation/public'


class Command(BaseCommand):
    help = 'Prepara lote de curadoria IA em modo controlado, sem envio real.'

    def add_arguments(self, parser):
        parser.add_argument('--channel', default=DEFAULT_CHANNEL_CODE, help='Código do canal social.')
        parser.add_argument(
            '--mode',
            choices=[choice[0] for choice in CurationRun.Mode.choices],
            default=CurationRun.Mode.DRY_RUN,
            help='Modo da curadoria: shadow, dry_run, homolog ou production.',
        )
        parser.add_argument('--dry-run', action='store_true', help='Força modo dry_run. Não envia nada.')
        parser.add_argument('--shadow', action='store_true', help='Força modo shadow. Não envia nada.')
        parser.add_argument('--candidate-limit', type=int, default=50, help='Quantidade máxima de candidatas.')
        parser.add_argument('--skip-images', action='store_true', help='Não preparar análise/processamento de imagens nesta etapa.')
        parser.add_argument('--audit-dir', default=os.environ.get('AI_CURATION_AUDIT_DIR', DEFAULT_AUDIT_DIR))
        parser.add_argument('--public-dir', default=os.environ.get('AI_CURATION_PUBLIC_DIR', DEFAULT_PUBLIC_DIR))

    def handle(self, *args, **options):
        candidate_limit = options['candidate_limit']
        if candidate_limit < 1:
            raise CommandError('--candidate-limit deve ser maior que zero.')

        mode = options['mode']
        if options['dry_run']:
            mode = CurationRun.Mode.DRY_RUN
        if options['shadow']:
            mode = CurationRun.Mode.SHADOW

        channel = self._get_channel(options['channel'])
        offers = self._get_candidates(channel=channel, limit=candidate_limit)
        if not offers:
            raise CommandError(f'Nenhuma oferta elegível encontrada para channel={channel.code}.')

        observer_context = {
            'source': 'prepare_ai_curation_batch_command',
            'skip_images': bool(options['skip_images']),
            'real_send_enabled': False,
        }
        result = prepare_ai_curation_batch(
            channel=channel,
            offers=offers,
            mode=mode,
            batch_size=min(20, len(offers)),
            audit_dir=Path(options['audit_dir']),
            public_json_dir=Path(options['public_dir']),
            observer_context=observer_context,
        )

        run = result.run
        self.stdout.write(f'Run #{run.id}: status={run.status} mode={run.mode} channel={channel.code}')
        self.stdout.write(f'Candidatas: {run.candidate_count}; selecionadas: {run.selected_count}')
        if result.batch:
            self.stdout.write(f'Batch #{result.batch.id}: status={result.batch.status} items={result.batch.items.count()}')
            self.stdout.write(f'Distribuição: {result.batch.actual_distribution_json}')
            if options['skip_images']:
                self.stdout.write('Imagens: puladas por --skip-images')
            else:
                image_result = process_selected_batch_images(
                    result.batch,
                    media_root=Path(getattr(settings, 'MEDIA_ROOT', 'media')),
                )
                self.stdout.write(
                    f'Imagens: processed={image_result.processed} failed={image_result.failed} skipped={image_result.skipped}'
                )
        if run.public_json_path:
            self.stdout.write(f'JSON público: {run.public_json_path}')
        if run.error_message:
            self.stdout.write(self.style.ERROR(run.error_message))
        self.stdout.write(self.style.WARNING('dry-run/controlado: nenhum envio real foi chamado.'))

    def _get_channel(self, code: str) -> SocialChannel:
        try:
            return SocialChannel.objects.get(code=code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(f'Canal não encontrado: {code}') from exc

    def _get_candidates(self, *, channel: SocialChannel, limit: int):
        config = get_selection_config()
        queryset = _eligible_offers(channel, config).select_related('marketplace', 'category')
        return list(queryset[:limit])
