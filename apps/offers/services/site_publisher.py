import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.curation.services.blacklist import filter_blacklisted_offers
from apps.offers.models import Offer
from apps.offers.services.freshness import get_freshness_cutoff, resolve_max_age_hours


DISCLOSURE = 'Como Associado da Amazon, ganho por compras qualificadas.'
DEFAULT_COMMIT_MESSAGE = 'chore: publish offers json'
GENERATED_AT_FIELD = 'generated_at'
PUBLISH_WORKTREE_DIRNAME = '.publish-worktree'
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishResult:
    generated: bool
    changed: bool
    output_path: str
    offers_count: int
    committed: bool = False
    pushed: bool = False
    message: str = ''
    error: str = ''
    git_stdout: str = ''
    git_stderr: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {
            'generated': self.generated,
            'changed': self.changed,
            'committed': self.committed,
            'pushed': self.pushed,
            'offers_count': self.offers_count,
            'output_path': self.output_path,
            'message': self.message,
            'error': self.error,
            'git_stdout': self.git_stdout,
            'git_stderr': self.git_stderr,
        }


class GitCommandError(RuntimeError):
    def __init__(self, message: str, stdout: str = '', stderr: str = ''):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def build_offers_payload() -> dict[str, Any]:
    site_base_url = settings.PUBLIC_SITE_BASE_URL.rstrip('/')
    offers = [
        _serialize_offer(offer)
        for offer in _get_publishable_offers()
    ]
    return {
        'version': '2.0',
        'generated_at': timezone.now().isoformat(),
        'site_base_url': site_base_url,
        'disclosure': DISCLOSURE,
        'offers': offers,
    }


def publish_offers(
    output_path: str | Path | None = None,
    push: bool = True,
    branch: str | None = None,
) -> dict[str, Any]:
    export_path = Path(output_path or settings.OFFERS_EXPORT_PATH)
    public_path = Path(settings.OFFERS_JSON_OUTPUT_PATH)
    if not public_path.is_absolute():
        public_path = Path(settings.BASE_DIR) / public_path
    links_path = Path(settings.LINKS_JSON_OUTPUT_PATH)
    if not links_path.is_absolute():
        links_path = Path(settings.BASE_DIR) / links_path
    generated = False
    changed = False
    offers_count = 0

    try:
        payload = build_offers_payload()
        generated = True
        offers_count = len(payload['offers'])
        offers_changed = _has_real_payload_change(public_path, payload)

        links_payload, links_error = _build_links_payload_safe()
        links_changed = (
            links_payload is not None
            and _has_real_payload_change(links_path, links_payload)
        )

        if export_path.resolve() != public_path.resolve():
            _write_json(export_path, payload)

        changed = offers_changed or links_changed
        if not changed:
            message = 'Sem alteração real em offers.json ou links.json; commit e push ignorados.'
            log.info(message)
            return PublishResult(
                generated=True,
                changed=False,
                output_path=str(public_path),
                offers_count=offers_count,
                message=message,
            ).as_dict()

        commit_paths: list[Path] = []
        if offers_changed:
            _write_json(public_path, payload)
            commit_paths.append(public_path)
            log.info('offers.json atualizado caminho=%s', public_path)
        if links_changed and links_payload is not None:
            _write_json(links_path, links_payload)
            commit_paths.append(links_path)
            log.info(
                'links.json atualizado itens=%s caminho=%s',
                len(links_payload['items']),
                links_path,
            )
        if links_error:
            log.warning('links.json não pôde ser gerado: %s', links_error)

        if not push:
            return PublishResult(
                generated=True,
                changed=True,
                output_path=str(public_path),
                offers_count=offers_count,
                message='offers.json/links.json atualizados localmente; push desabilitado.',
            ).as_dict()

        pushed, committed = _commit_and_push(commit_paths, branch=branch)
        if not committed:
            message = 'Sem diff rastreável no Git após atualizar offers.json/links.json.'
        elif pushed:
            message = 'offers.json/links.json commitados e enviados ao repositório remoto.'
        else:
            message = 'offers.json/links.json commitados; push não executado.'

        return PublishResult(
            generated=True,
            changed=True,
            output_path=str(public_path),
            offers_count=offers_count,
            committed=committed,
            pushed=pushed,
            message=message,
        ).as_dict()
    except GitCommandError as exc:
        log.error(
            'Falha de Git ao publicar offers.json: %s stdout=%s stderr=%s',
            exc,
            exc.stdout,
            exc.stderr,
        )
        return PublishResult(
            generated=generated,
            changed=changed,
            output_path=str(public_path),
            offers_count=offers_count,
            message='Falha de Git ao publicar offers.json.',
            error=str(exc),
            git_stdout=exc.stdout,
            git_stderr=exc.stderr,
        ).as_dict()
    except Exception as exc:
        log.exception('Falha ao gerar ou gravar offers.json.')
        return PublishResult(
            generated=generated,
            changed=changed,
            output_path=str(public_path),
            offers_count=offers_count,
            message='Falha ao gerar ou gravar offers.json.',
            error=str(exc),
        ).as_dict()


def _get_publishable_offers():
    """Ofertas exibíveis no site público.

    Aplica corte de recência (`last_seen_at`) e ordenação determinística:
    `last_seen_at` desc, `discount_pct` desc, `title` asc. Ofertas fora da
    janela permanecem persistidas; só são omitidas da publicação.
    """
    max_age_hours = resolve_max_age_hours()
    cutoff = get_freshness_cutoff()

    base_qs = (
        Offer.objects
        .select_related('marketplace')
        .filter(is_active=True, slug__isnull=False)
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
    )
    total_before = base_qs.count()

    eligible_qs = base_qs.filter(last_seen_at__gte=cutoff).order_by(
        '-last_seen_at',
        '-discount_pct',
        'title',
        'id',
    )
    total_eligible = eligible_qs.count()
    skipped = total_before - total_eligible

    publishable_offers = filter_blacklisted_offers(list(eligible_qs))
    blocked_by_blacklist = total_eligible - len(publishable_offers)

    log.info(
        'Publicação offers.json: cutoff=%s janela_horas=%s total_antes=%s '
        'elegiveis=%s ignoradas_por_expiracao=%s bloqueadas_por_blacklist=%s '
        '(registros antigos preservados no banco).',
        cutoff.isoformat(),
        max_age_hours,
        total_before,
        total_eligible,
        skipped,
        blocked_by_blacklist,
    )

    return publishable_offers


def _serialize_offer(offer: Offer) -> dict[str, Any]:
    return {
        'id': offer.id,
        'slug': offer.slug,
        'marketplace': {
            'code': offer.marketplace.code,
            'name': offer.marketplace.name,
        },
        'title': offer.title,
        'short_description': offer.short_description,
        'current_price': _decimal_to_string(offer.current_price),
        'original_price': _decimal_to_string(offer.original_price),
        'discount_pct': _decimal_to_string(offer.discount_pct),
        'image_url': offer.image_url,
        'affiliate_link': offer.affiliate_link,
        'detail_url': f'/oferta?slug={offer.slug}',
        'price_collected_at': offer.price_collected_at.isoformat() if offer.price_collected_at else '',
    }


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal('0.01')))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def _has_real_payload_change(path: Path, payload: dict[str, Any]) -> bool:
    if not path.exists():
        return True

    try:
        current_payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        log.warning('offers.json atual não pôde ser lido; será regenerado: %s', path)
        return True

    return _stable_payload(current_payload) != _stable_payload(payload)


def _stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stable = dict(payload)
    stable.pop(GENERATED_AT_FIELD, None)
    return stable


def _build_links_payload_safe() -> tuple[dict[str, Any] | None, str]:
    """Gera payload de links.json sem propagar exceções.

    Falha de geração (ex.: poucas ofertas dentro da janela) não deve abortar
    a publicação de offers.json — links.json é complementar.
    """
    # Import local pra evitar ciclo de import com apps.offers no boot.
    from apps.social_posts.services.bio_link_publisher import build_links_payload

    try:
        return build_links_payload(count=settings.LINKS_JSON_ITEMS_COUNT), ''
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _commit_and_push(
    public_paths: list[Path],
    branch: str | None = None,
) -> tuple[bool, bool]:
    if not public_paths:
        return False, False

    repo_path = Path(settings.SITE_REPO_LOCAL_PATH).resolve()
    if not repo_path.exists():
        raise GitCommandError(f'Repositório integrado não encontrado: {repo_path}')

    branch = branch or settings.PUBLISH_OFFERS_BRANCH

    public_dir = Path(settings.SITE_PUBLIC_DIR)
    if not public_dir.is_absolute():
        public_dir = repo_path / public_dir

    # Worktree dedicado em PUBLISH_OFFERS_BRANCH desacopla o publish do branch
    # checado no working tree principal. Sem isso, se o operador trocar de
    # branch (ex.: trabalhar numa feature), o commit cai no branch errado e o
    # `push origin <branch>` empurra o tip local de <branch> — que ninguém
    # atualizou — virando no-op silencioso. Resultado: produção (Vercel deploy
    # de origin/main) congela sem erro visível.
    worktree_path = _ensure_publish_worktree(repo_path, branch)

    git_paths: list[str] = []
    for public_path in public_paths:
        target_path = public_path.resolve()
        if not _is_relative_to(target_path, repo_path):
            target_path = public_dir / public_path.name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(public_path, target_path)

        relative_path = target_path.relative_to(repo_path)
        worktree_target = worktree_path / relative_path
        worktree_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target_path, worktree_target)
        git_paths.append(relative_path.as_posix())

    diff_paths = [p for p in git_paths if _has_diff(worktree_path, p)]
    if not diff_paths:
        return False, False

    for git_path in diff_paths:
        _run_git(worktree_path, 'add', git_path)
    _run_git(
        worktree_path,
        '-c',
        'user.name=descontos.bot',
        '-c',
        'user.email=bot@descontos.bot',
        'commit',
        '-m',
        DEFAULT_COMMIT_MESSAGE,
    )
    _run_git(worktree_path, 'push', 'origin', f'HEAD:{branch}')
    return True, True


def _ensure_publish_worktree(repo_path: Path, branch: str) -> Path:
    """Garante worktree dedicado para o publish, em HEAD destacado no tip remoto.

    O worktree fica em ``<repo>/.publish-worktree`` (ignorado pelo Git). Usamos
    HEAD destacado em ``origin/<branch>`` em vez de ``checkout <branch>`` para
    não colidir com o working tree principal — só um working tree pode ter
    determinado branch checado por vez. Cada ciclo reseta o worktree a
    ``origin/<branch>`` (descartando qualquer commit local pendente de ciclo
    anterior), garantindo que o publish parta sempre de um ponto conhecido.
    """
    worktree_path = repo_path / PUBLISH_WORKTREE_DIRNAME
    _run_git(repo_path, 'fetch', 'origin', branch)

    if not (worktree_path / '.git').exists():
        _run_git(
            repo_path,
            'worktree',
            'add',
            '--detach',
            str(worktree_path),
            f'origin/{branch}',
        )

    _run_git(worktree_path, 'fetch', 'origin', branch)
    _run_git(worktree_path, 'reset', '--hard', f'origin/{branch}')
    return worktree_path


def _has_diff(repo_path: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ['git', 'status', '--short', '--', relative_path],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _run_git(repo_path: Path, *args: str) -> None:
    result = subprocess.run(
        ['git', *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        command = ' '.join(['git', *args])
        raise GitCommandError(
            f'Comando Git falhou ({result.returncode}): {command}',
            stdout=result.stdout,
            stderr=result.stderr,
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
