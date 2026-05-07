import logging

from django.conf import settings

from apps.offers.services.site_publisher import publish_offers


log = logging.getLogger(__name__)


def get_auto_publish_skip_reason(total_valid: int, dry_run: bool = False) -> str:
    if not settings.PUBLISH_OFFERS_AFTER_CAPTURE:
        return 'Publicação automática ignorada: PUBLISH_OFFERS_AFTER_CAPTURE=false.'

    if dry_run:
        return 'Publicação automática ignorada: dry_run ativo.'

    if total_valid <= 0:
        return 'Publicação automática ignorada: captura sem ofertas válidas atualizadas.'

    return ''


def publish_offers_after_capture() -> dict:
    log.info(
        'Publicação automática iniciada. push=%s branch=%s',
        settings.PUBLISH_OFFERS_PUSH,
        settings.PUBLISH_OFFERS_BRANCH,
    )
    return publish_offers(
        push=settings.PUBLISH_OFFERS_PUSH,
        branch=settings.PUBLISH_OFFERS_BRANCH,
    )
