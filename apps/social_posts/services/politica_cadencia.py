"""Política de cadência de geração de conteúdo Instagram (Sprint 7 - Tarefa 7.2).

Contexto (achado C4): a geração automática (`run_bot`) e os comandos manuais de
Instagram foram desativados em 2026-07-09 via `return` antecipado, sem que
nenhum limite de cadência os protegesse de rajada quando fossem reativados.
`docs/ROTINA_EDITORIAL_INSTAGRAM.md` (seção 2) já documenta os volumes-alvo
desde a Sprint 4 antiga — 3 stories/dia + 1 feed-ou-carrossel/dia — mas de
forma só manual/aspiracional (dependia do operador não rodar os geradores
demais vezes). Este módulo torna esse teto REALMENTE aplicado em código,
seguindo o mesmo padrão de
`apps.orchestration.services.scheduler.get_channel_cadence_config`: dataclass
frozen de config + `get_integer_setting` para permitir override via Setting
do painel (ou env, indiretamente) sem precisar de redeploy.

Enforcement fica em `apps.social_posts.services.post_generator` (chamado por
`run_bot` E pelos comandos manuais `generate_instagram_story/post/carousel`)
para que nenhum ponto de entrada consiga contornar o teto.
"""

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.curation.services.settings import get_integer_setting
from apps.social_posts.models import InstagramPost

log = logging.getLogger(__name__)

# Defaults alinhados ao volume já documentado em docs/ROTINA_EDITORIAL_INSTAGRAM.md
# (seção 2, "Volumes Semanais"): 3 stories/dia (21/semana) e 1 feed-ou-carrossel/dia
# (7/semana). Não são números novos — só passam a ser aplicados em código.
DEFAULT_STORY_DAILY_LIMIT = 3
DEFAULT_FEED_OR_CAROUSEL_DAILY_LIMIT = 1

STORY_DAILY_LIMIT_SETTING_KEY = 'instagram_story_daily_limit'
FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY = 'instagram_feed_or_carousel_daily_limit'


class CadenciaExcedidaError(RuntimeError):
    """Teto diário de geração de conteúdo Instagram já foi atingido hoje."""


@dataclass(frozen=True)
class CadenciaInstagramConfig:
    story_daily_limit: int
    feed_or_carousel_daily_limit: int


def get_cadencia_config() -> CadenciaInstagramConfig:
    story_limit = get_integer_setting(STORY_DAILY_LIMIT_SETTING_KEY, DEFAULT_STORY_DAILY_LIMIT)
    feed_limit = get_integer_setting(
        FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY, DEFAULT_FEED_OR_CAROUSEL_DAILY_LIMIT,
    )
    return CadenciaInstagramConfig(
        story_daily_limit=max(0, story_limit),
        feed_or_carousel_daily_limit=max(0, feed_limit),
    )


def pode_gerar_story(*, config: CadenciaInstagramConfig | None = None) -> bool:
    """False quando o teto diário de stories (`InstagramPost.Format.STORY`) já foi atingido."""
    config = config or get_cadencia_config()
    if config.story_daily_limit <= 0:
        log.info('instagram_cadencia.story_limite_zero')
        return False
    hoje = _contagem_hoje(InstagramPost.Format.STORY)
    if hoje >= config.story_daily_limit:
        log.info('instagram_cadencia.story_teto_atingido hoje=%s teto=%s', hoje, config.story_daily_limit)
        return False
    return True


def pode_gerar_feed_ou_carrossel(*, config: CadenciaInstagramConfig | None = None) -> bool:
    """False quando o teto diário combinado de feed OU carrossel já foi atingido.

    O teto é compartilhado entre os dois formatos (1 feed-ou-carrossel/dia, não
    1 de cada) — mesma semântica já documentada na Rotina Editorial.
    """
    config = config or get_cadencia_config()
    if config.feed_or_carousel_daily_limit <= 0:
        log.info('instagram_cadencia.feed_ou_carrossel_limite_zero')
        return False
    hoje = InstagramPost.objects.filter(
        format__in=[InstagramPost.Format.FEED, InstagramPost.Format.CAROUSEL],
        created_at__date=timezone.localdate(),
    ).count()
    if hoje >= config.feed_or_carousel_daily_limit:
        log.info(
            'instagram_cadencia.feed_ou_carrossel_teto_atingido hoje=%s teto=%s',
            hoje, config.feed_or_carousel_daily_limit,
        )
        return False
    return True


def exigir_cota_story() -> None:
    """Levanta `CadenciaExcedidaError` se o teto diário de stories já foi atingido."""
    config = get_cadencia_config()
    if not pode_gerar_story(config=config):
        raise CadenciaExcedidaError(
            f'Teto diário de stories do Instagram atingido ({config.story_daily_limit}/dia). '
            f'Ajustável via Setting "{STORY_DAILY_LIMIT_SETTING_KEY}" no painel.',
        )


def exigir_cota_feed_ou_carrossel() -> None:
    """Levanta `CadenciaExcedidaError` se o teto diário de feed/carrossel já foi atingido."""
    config = get_cadencia_config()
    if not pode_gerar_feed_ou_carrossel(config=config):
        raise CadenciaExcedidaError(
            'Teto diário de feed/carrossel do Instagram atingido '
            f'({config.feed_or_carousel_daily_limit}/dia). Ajustável via Setting '
            f'"{FEED_OR_CAROUSEL_DAILY_LIMIT_SETTING_KEY}" no painel.',
        )


def _contagem_hoje(post_format: str) -> int:
    return InstagramPost.objects.filter(
        format=post_format,
        created_at__date=timezone.localdate(),
    ).count()
