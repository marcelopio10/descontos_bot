"""Publica no Instagram, em lote, o que está aguardando publicação.

Item 10 da Onda 2. O Instagram gera desde sempre e publicou 5 posts — o último em
2026-06-03. Não é credencial: o preflight do Composio responde
(`manage.py check_instagram_composio`). É que **não existia caminho em lote**:
`publish_instagram_post` publica um post por vez, com `--confirm-production`
individual, e o listener de handoff do Telegram não roda. Resultado: 89 posts
parados em `awaiting_post`.

Duas travas de propósito, porque aqui se publica na conta real de um terceiro
(o Instagram do dono):

1. **Publicação real exige `--confirm-production`.** Sem a flag, roda em modo de
   simulação e não chama o Composio.
2. **Backlog velho não é publicado.** Post de oferta que saiu do ar ou envelheceu
   é descartado da fila em vez de ir ao ar: a maior parte dos 89 acumulados é de
   junho e julho, e publicar preço morto queima a conta que deveria trazer
   público.

    manage.py publicar_instagram_lote                          # simulação
    manage.py publicar_instagram_lote --limit 2 --confirm-production
    manage.py publicar_instagram_lote --formato story --max-age-days 2
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.offers.services.freshness import get_freshness_cutoff
from apps.social_posts.models import InstagramPost
from apps.social_posts.services.composio_publisher import (
    ComposioPublishError,
    ComposioPublishUnknownError,
    publish_post,
    record_failure,
    record_unknown_failure,
)
from apps.social_posts.services.politica_cadencia import get_cadencia_config

DEFAULT_LIMIT = 3
DEFAULT_MAX_AGE_DAYS = 3
FORMATOS_PUBLICAVEIS = (InstagramPost.Format.FEED, InstagramPost.Format.STORY)


class Command(BaseCommand):
    help = (
        'Publica em lote os InstagramPost em awaiting_post, respeitando a '
        'cadência diária e descartando post de oferta velha. Simula por padrão.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=DEFAULT_LIMIT,
            help=f'Máximo de posts nesta execução (default: {DEFAULT_LIMIT}).',
        )
        parser.add_argument(
            '--formato',
            choices=[f.value for f in FORMATOS_PUBLICAVEIS],
            help='Restringe a um formato. Sem isso, publica feed e story.',
        )
        parser.add_argument(
            '--max-age-days',
            type=int,
            default=DEFAULT_MAX_AGE_DAYS,
            help=(
                'Idade máxima do post em dias '
                f'(default: {DEFAULT_MAX_AGE_DAYS}). Post mais velho é pulado.'
            ),
        )
        parser.add_argument(
            '--confirm-production',
            action='store_true',
            help='Autoriza a publicação real. Sem isso, só simula.',
        )

    def handle(self, *args, **options):
        limite = options['limit']
        simulacao = not options['confirm_production']
        candidatos, descartados = self._candidatos(options)

        if simulacao:
            self.stdout.write(self.style.WARNING(
                'MODO SIMULAÇÃO — nada será publicado. Use --confirm-production '
                'para publicar de verdade.'
            ))

        self.stdout.write(
            f'Fila: {InstagramPost.objects.filter(status=InstagramPost.Status.AWAITING_POST).count()} '
            f'em awaiting_post · {len(candidatos)} publicáveis agora · '
            f'{descartados} descartados por idade ou oferta fora do ar'
        )

        cotas = self._cotas_restantes()
        publicados = 0
        for post in candidatos:
            if publicados >= limite:
                break
            if cotas.get(post.format, 0) <= 0:
                self.stdout.write(
                    f'  · #{post.id} ({post.format}) pulado: cota diária do formato esgotada.'
                )
                continue

            if simulacao:
                self.stdout.write(
                    f'  [simulado] #{post.id} {post.format} — '
                    f'{(post.caption or "")[:60]!r}'
                )
            else:
                if not self._publicar(post):
                    continue

            cotas[post.format] -= 1
            publicados += 1

        verbo = 'simulados' if simulacao else 'publicados'
        self.stdout.write(self.style.SUCCESS(f'{publicados} post(s) {verbo}.'))

    def _candidatos(self, options) -> tuple[list[InstagramPost], int]:
        """Fila publicável, do mais novo para o mais velho.

        Do mais novo de propósito: a fila tem meses de acúmulo, e o post recente
        é o que ainda descreve uma oferta viva.
        """
        formatos = [options['formato']] if options['formato'] else [
            f.value for f in FORMATOS_PUBLICAVEIS
        ]
        limite_idade = timezone.now() - timedelta(days=options['max_age_days'])
        cutoff_oferta = get_freshness_cutoff()

        fila = (
            InstagramPost.objects
            .filter(status=InstagramPost.Status.AWAITING_POST, format__in=formatos)
            .select_related('primary_offer')
            .order_by('-created_at')
        )

        candidatos: list[InstagramPost] = []
        descartados = 0
        for post in fila:
            oferta = post.primary_offer
            velho = post.created_at < limite_idade
            oferta_morta = (
                oferta is None
                or not oferta.is_active
                or (oferta.last_seen_at and oferta.last_seen_at < cutoff_oferta)
            )
            if velho or oferta_morta:
                descartados += 1
                continue
            candidatos.append(post)

        return candidatos, descartados

    def _cotas_restantes(self) -> dict[str, int]:
        """Cota diária por formato, contando o que já foi PUBLICADO hoje.

        A `politica_cadencia` conta o que foi **gerado** no dia — é cota de
        geração. Aqui a pergunta é outra: quanto ainda pode ir ao ar hoje. Os
        tetos são os mesmos de propósito, para a cadência editorial não ter dois
        números diferentes.
        """
        config = get_cadencia_config()
        hoje = timezone.localdate()
        publicados_hoje = {
            formato.value: InstagramPost.objects.filter(
                format=formato.value,
                status=InstagramPost.Status.POSTED,
                posted_at__date=hoje,
            ).count()
            for formato in FORMATOS_PUBLICAVEIS
        }
        return {
            InstagramPost.Format.STORY.value: max(
                0, config.story_daily_limit - publicados_hoje[InstagramPost.Format.STORY.value]
            ),
            InstagramPost.Format.FEED.value: max(
                0,
                config.feed_or_carousel_daily_limit
                - publicados_hoje[InstagramPost.Format.FEED.value],
            ),
        }

    def _publicar(self, post: InstagramPost) -> bool:
        try:
            result = publish_post(post)
        except ComposioPublishUnknownError as exc:
            record_unknown_failure(post, str(exc))
            self.stdout.write(self.style.ERROR(
                f'  ! #{post.id}: resultado desconhecido ({exc}). '
                'Conferir no Instagram antes de tentar de novo.'
            ))
            return False
        except ComposioPublishError as exc:
            record_failure(post, str(exc))
            self.stdout.write(self.style.ERROR(f'  ! #{post.id}: falhou ({exc}).'))
            return False

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ #{post.id} {post.format} publicado (media_id={result.media_id}).'
        ))
        return True
