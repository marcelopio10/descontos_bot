from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curation.models import CurationRun
from apps.curation.services.ai_curator import prepare_ai_curation_batch
from apps.curation.services.batch_optimizer import DEFAULT_TARGET_DISTRIBUTION
from apps.curation.services.hermes_runner import HermesProfileRunner
from apps.curation.services.image_processing import process_selected_batch_images
from apps.curation.services.observer_context import assert_sanitized_context, build_observer_context
from apps.curation.services.product_family import offer_family_key
from apps.curation.services.recurrence import filter_blocked_recurrence, filter_saturated_families
from apps.curation.services.selector import _eligible_offers, get_selection_config
from apps.distribution.models import SocialChannel
from apps.marketplaces.services.radar_mercado import collect_radar_mercado
from apps.marketplaces.services.search_radar import build_search_radar

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
        parser.add_argument('--runner', choices=['mock', 'real'], default='mock', help='Runner Hermes: mock determinístico ou profile real.')
        parser.add_argument('--profile', default='descontos-bot', help='Profile Hermes usado quando --runner=real.')
        parser.add_argument('--model', default='', help='Sobrescreve o modelo do profile Hermes (ex.: glm-5.2). Vazio = modelo padrão do profile.')
        parser.add_argument('--provider', default='', help='Sobrescreve o provider de inferência do Hermes (opcional).')
        parser.add_argument('--runner-timeout', type=int, default=600, help='Timeout em segundos para Hermes CLI real.')
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

        # Sprint 6 / Tarefa 6.2 (achado P3): antes disto era um dict estático
        # (nunca refletia o que o observer via de fato); agora é
        # build_observer_context() de verdade — mesclado com os 3 campos que
        # já existiam antes desta tarefa. `source`/`skip_images`/
        # `real_send_enabled` são metadados DESTE comando (não são sinal do
        # observer), por isso ficam por cima do spread: se algum dia um campo
        # colidir, o metadado explícito do comando vence sobre o agregado
        # genérico. `assert_sanitized_context` reaplica a validação
        # anti-vazamento (LGPD) sobre o dict final já mesclado — defesa extra
        # e barata contra um futuro campo de metadado sensível ser adicionado
        # aqui sem passar pela sanitização de `build_observer_context`.
        observer_context = assert_sanitized_context({
            **build_observer_context(),
            'search_radar': build_search_radar(),
            'source': 'prepare_ai_curation_batch_command',
            'skip_images': bool(options['skip_images']),
            'real_send_enabled': False,
        })

        # Sprint 6 / Tarefa 6.1 (achado P7): ranking de vendas Shopee do dia.
        # `collect_radar_mercado()` já se auto-protege por
        # `settings.SHOPEE_AFFILIATE_ENABLED` (off por padrão em produção
        # hoje) e devolve um resultado vazio/neutro sem chamar a API nesse
        # caso — não muda nada em produção enquanto a flag estiver desligada.
        # Nota para quando a flag for ligada: este comando roda a cada ciclo
        # de curadoria (não só 1x/dia), então religar a flag reabre a
        # pergunta de cadência de chamadas à API Shopee aqui — decisão futura
        # do dono, fora do escopo desta tarefa.
        market_radar = collect_radar_mercado().as_dict()

        runner = None
        profile_name = 'mock'
        model_provider = 'mock'
        model_name = 'fake-hermes-runner'
        if options['runner'] == 'real':
            profile_name = options['profile']
            model_override = options['model'].strip() or None
            provider_override = options['provider'].strip() or None
            model_provider = provider_override or 'openai-codex'
            model_name = model_override or 'gpt-5.5'
            runner = HermesProfileRunner(
                profile_name=profile_name,
                timeout_seconds=options['runner_timeout'],
                model_override=model_override,
                provider_override=provider_override,
            )

        result = prepare_ai_curation_batch(
            channel=channel,
            offers=offers,
            runner=runner,
            mode=mode,
            batch_size=min(20, len(offers)),
            audit_dir=Path(options['audit_dir']),
            public_json_dir=Path(options['public_dir']),
            observer_context=observer_context,
            market_radar=market_radar,
            profile_name=profile_name,
            model_provider=model_provider,
            model_name=model_name,
        )

        run = result.run
        self.stdout.write(f'Run #{run.id}: status={run.status} mode={run.mode} channel={channel.code} runner={options["runner"]}')
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
        if run.status == CurationRun.Status.FAILED:
            raise CommandError(
                f'prepare_ai_curation_batch falhou (run #{run.id}): {run.error_message or "run com status failed"}'
            )

    def _get_channel(self, code: str) -> SocialChannel:
        try:
            return SocialChannel.objects.get(code=code)
        except SocialChannel.DoesNotExist as exc:
            raise CommandError(f'Canal não encontrado: {code}') from exc

    def _get_candidates(self, *, channel: SocialChannel, limit: int):
        config = get_selection_config()
        queryset = _eligible_offers(channel, config).select_related('marketplace', 'category')
        recent_ok = filter_blocked_recurrence(queryset, channel)
        return _balanced_marketplace_candidates(
            filter_saturated_families(recent_ok, channel),
            limit=limit,
        )


CANDIDATE_OVERFETCH_MULTIPLIER = 3  # margem para compensar itens descartados pelo dedup de produto canônico

# Teto de candidatas da mesma família no payload enviado ao agente (achado
# 2026-08-21). Sem isto, um pool de 50 candidatas chegava com ~13% de tênis
# (era o que a coleta trazia) e a IA escolhia entre variações do mesmo produto
# achando que estava diversificando. Não é 1 porque o pool é matéria-prima, não
# lote final: manter 2 dá margem para a IA descartar uma por segurança/qualidade
# e ainda ter a família representada.
CANDIDATE_MAX_PER_FAMILY = 2


def _balanced_marketplace_candidates(queryset, *, limit: int):
    """Build the AI candidate pool with marketplace coverage before the agent runs.

    The AI remains the curator, but it cannot pick Shopee if the candidate payload
    is filled by higher-discount ML/Amazon rows before Shopee appears. Seed the
    payload near the target mix, then fill shortages from the global order.

    Also applies a light pre-filter (Sprint 5 / achado P8) that skips offers
    whose `produto_canonico_id` already appears earlier in the pool (queryset
    ordering already favors higher discount first, so "earlier" means "best"),
    so we don't waste candidate slots sending the AI an obvious duplicate
    (e.g. the same Amazon ASIN via two sellers). This is only a pool-shaping
    optimization — the actual source of truth for dedup is
    apps.curation.services.batch_optimizer.optimize_curation_batch, which runs
    after the AI decides and is what final selection actually depends on.
    """
    if limit <= 0:
        return []
    quotas = _target_counts(limit, DEFAULT_TARGET_DISTRIBUTION)
    selected = []
    selected_ids: set[int] = set()
    seen_canonicos: set[str] = set()
    family_counts: dict[str, int] = {}
    is_materialized = isinstance(queryset, list)
    for marketplace_code in DEFAULT_TARGET_DISTRIBUTION:
        quota = quotas.get(marketplace_code, 0)
        if quota <= 0:
            continue
        candidates = (
            [offer for offer in queryset if offer.marketplace.code == marketplace_code][: quota * CANDIDATE_OVERFETCH_MULTIPLIER]
            if is_materialized
            else queryset.filter(marketplace__code=marketplace_code)[: quota * CANDIDATE_OVERFETCH_MULTIPLIER]
        )
        _append_diversified(candidates, quota, selected, selected_ids, seen_canonicos, family_counts)
    if len(selected) < limit:
        remaining_quota = limit - len(selected)
        remaining = (
            [offer for offer in queryset if offer.id not in selected_ids][: remaining_quota * CANDIDATE_OVERFETCH_MULTIPLIER]
            if is_materialized
            else queryset.exclude(id__in=selected_ids)[: remaining_quota * CANDIDATE_OVERFETCH_MULTIPLIER]
        )
        _append_diversified(remaining, remaining_quota, selected, selected_ids, seen_canonicos, family_counts)
    return selected[:limit]


def _append_diversified(candidates, quota, selected, selected_ids, seen_canonicos, family_counts):
    added = 0
    for offer in candidates:
        if added >= quota:
            break
        canonico = (offer.produto_canonico_id or '').strip()
        if canonico and canonico in seen_canonicos:
            continue
        family = offer_family_key(offer)
        if family and family_counts.get(family, 0) >= CANDIDATE_MAX_PER_FAMILY:
            continue
        selected.append(offer)
        selected_ids.add(offer.id)
        if canonico:
            seen_canonicos.add(canonico)
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
        added += 1


def _target_counts(limit: int, target_distribution: dict[str, float]) -> dict[str, int]:
    raw = {marketplace: limit * weight for marketplace, weight in target_distribution.items()}
    counts = {marketplace: int(value) for marketplace, value in raw.items()}
    missing = limit - sum(counts.values())
    remainders = sorted(raw.items(), key=lambda item: (-(item[1] - int(item[1])), item[0]))
    for marketplace, _ in remainders[:missing]:
        counts[marketplace] += 1
    return counts
