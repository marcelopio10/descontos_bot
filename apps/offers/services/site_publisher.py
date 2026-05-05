import json
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.offers.models import Offer


DISCLOSURE = 'Como Associado da Amazon, ganho por compras qualificadas.'


@dataclass(frozen=True)
class PublishResult:
    output_path: Path
    offers_count: int
    pushed: bool = False
    committed: bool = False


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


def publish_offers(output_path: str | Path | None = None, push: bool = False) -> PublishResult:
    payload = build_offers_payload()
    target_path = Path(output_path or settings.OFFERS_EXPORT_PATH)
    _write_json(target_path, payload)

    pushed = False
    committed = False
    if push:
        pushed, committed = _push_to_site_repo(target_path)

    return PublishResult(
        output_path=target_path,
        offers_count=len(payload['offers']),
        pushed=pushed,
        committed=committed,
    )


def _get_publishable_offers():
    return (
        Offer.objects
        .select_related('marketplace')
        .filter(is_active=True, slug__isnull=False)
        .exclude(slug='')
        .exclude(marketplace__code='amazon', asin='')
        .order_by('marketplace__code', '-discount_pct', 'title')
    )


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


def _push_to_site_repo(source_path: Path) -> tuple[bool, bool]:
    repo_path = Path(settings.SITE_REPO_LOCAL_PATH)
    if not repo_path.exists():
        raise FileNotFoundError(f'Repositório do site não encontrado: {repo_path}')

    target_path = repo_path / 'offers.json'
    shutil.copyfile(source_path, target_path)

    branch = settings.SITE_REPO_BRANCH
    _run_git(repo_path, 'pull', '--ff-only')

    if not _has_diff(repo_path, 'offers.json'):
        return True, False

    _run_git(repo_path, 'add', 'offers.json')
    _run_git(
        repo_path,
        '-c',
        'user.name=descontos.bot',
        '-c',
        'user.email=bot@descontos.bot',
        'commit',
        '-m',
        'chore: publish offers json',
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
    subprocess.run(
        ['git', *args],
        cwd=repo_path,
        check=True,
    )
