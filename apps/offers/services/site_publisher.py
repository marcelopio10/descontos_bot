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

from apps.offers.models import Offer
from apps.offers.services.freshness import get_freshness_cutoff, resolve_max_age_hours


DISCLOSURE = 'Como Associado da Amazon, ganho por compras qualificadas.'
DEFAULT_COMMIT_MESSAGE = 'chore: publish offers json'
GENERATED_AT_FIELD = 'generated_at'
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
    generated = False
    changed = False
    offers_count = 0

    try:
        payload = build_offers_payload()
        generated = True
        offers_count = len(payload['offers'])
        changed = _has_real_payload_change(public_path, payload)

        if export_path.resolve() != public_path.resolve():
            _write_json(export_path, payload)

        if not changed:
            message = 'Sem alteração real nas ofertas; commit e push ignorados.'
            log.info(message)
            return PublishResult(
                generated=True,
                changed=False,
                output_path=str(public_path),
                offers_count=offers_count,
                message=message,
            ).as_dict()

        _write_json(public_path, payload)
        message = 'offers.json atualizado com alteração real nas ofertas.'
        log.info('%s ofertas=%s caminho=%s', message, offers_count, public_path)

        if not push:
            return PublishResult(
                generated=True,
                changed=True,
                output_path=str(public_path),
                offers_count=offers_count,
                message='offers.json atualizado localmente; push desabilitado.',
            ).as_dict()

        pushed, committed = _commit_and_push(public_path, branch=branch)
        if not committed:
            message = 'Sem diff rastreável no Git após atualizar offers.json.'
        elif pushed:
            message = 'offers.json commitado e enviado ao repositório remoto.'
        else:
            message = 'offers.json commitado; push não executado.'

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

    log.info(
        'Publicação offers.json: cutoff=%s janela_horas=%s total_antes=%s '
        'elegiveis=%s ignoradas_por_expiracao=%s (registros antigos preservados no banco).',
        cutoff.isoformat(),
        max_age_hours,
        total_before,
        total_eligible,
        skipped,
    )

    return eligible_qs


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


def _commit_and_push(public_path: Path, branch: str | None = None) -> tuple[bool, bool]:
    repo_path = Path(settings.SITE_REPO_LOCAL_PATH).resolve()
    if not repo_path.exists():
        raise GitCommandError(f'Repositório integrado não encontrado: {repo_path}')

    target_path = public_path.resolve()
    if not _is_relative_to(target_path, repo_path):
        public_dir = Path(settings.SITE_PUBLIC_DIR)
        if not public_dir.is_absolute():
            public_dir = repo_path / public_dir
        target_path = public_dir / 'offers.json'
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(public_path, target_path)

    branch = branch or settings.PUBLISH_OFFERS_BRANCH
    _run_git(repo_path, 'pull', '--ff-only', 'origin', branch)

    relative_path = target_path.relative_to(repo_path)
    git_path = relative_path.as_posix()

    if not _has_diff(repo_path, git_path):
        return False, False

    _run_git(repo_path, 'add', git_path)
    _run_git(
        repo_path,
        '-c',
        'user.name=descontos.bot',
        '-c',
        'user.email=bot@descontos.bot',
        'commit',
        '-m',
        DEFAULT_COMMIT_MESSAGE,
    )
    _run_git(repo_path, 'push', 'origin', branch)
    return True, True


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
