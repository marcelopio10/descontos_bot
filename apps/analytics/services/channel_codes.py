from apps.distribution.models import SocialChannel


_SHORT_PREFIX_TO_FULL: dict[str, tuple[str, ...]] = {
    'wa': ('whatsapp_', 'whatsapp_channel_', 'whatsapp_group_'),
    'tg': ('telegram_', 'telegram_channel_'),
}


def expand_short_channel_code(short_code: str) -> SocialChannel | None:
    """Inverso de `link_builder._short_channel_code`.

    Recebe o trecho curto que aparece no SubID ML (ex: `wa_main`, `tg_homolog`
    ou um channel.code completo) e devolve o SocialChannel correspondente.

    O encurtamento é ambíguo (wa_main pode ser whatsapp_main, whatsapp_channel_main
    ou whatsapp_group_main). Resolvemos pela primeira ocorrência ativa no banco.
    """
    if not short_code:
        return None

    direct = SocialChannel.objects.filter(code=short_code).first()
    if direct:
        return direct

    prefix, _, suffix = short_code.partition('_')
    candidate_prefixes = _SHORT_PREFIX_TO_FULL.get(prefix)
    if not candidate_prefixes or not suffix:
        return None

    candidate_codes = [f'{full_prefix}{suffix}' for full_prefix in candidate_prefixes]
    return (
        SocialChannel.objects.filter(code__in=candidate_codes)
        .order_by('-is_enabled', 'id')
        .first()
    )
