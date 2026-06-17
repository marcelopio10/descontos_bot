"""Disclosure publicitário e bloqueio de clickbait por marketplace.

Centraliza regras de copy para WhatsApp, Telegram e site. A identificação
publicitária por publicação foi desativada para não inserir hashtag na caption
da oferta; disclosures permanentes ficam nos canais/site quando aplicável.
"""

# Marketplaces que exigem selo publicitário explícito em toda publicação.
AD_DISCLOSURE_MARKETPLACES: set[str] = set()

AD_DISCLOSURE_TAG = '#publicidade'

# Frases proibidas (alarmismo / clickbait / promessa enganosa).
BLOCKED_COPY_FRAGMENTS = (
    'clique obrigatório',
    'clique obrigatorio',
    'você ganhou',
    'voce ganhou',
    'última chance garantida',
    'ultima chance garantida',
    'grátis garantido',
    'gratis garantido',
    'shopee está dando de graça',
    'shopee esta dando de graca',
)


def requires_ad_disclosure(marketplace_code: str | None) -> bool:
    return (marketplace_code or '').strip().lower() in AD_DISCLOSURE_MARKETPLACES


def ad_disclosure_prefix(marketplace_code: str | None, suffix: str = '\n\n') -> str:
    """Prefixo de disclosure para o início da mensagem; vazio quando não exigido."""
    if requires_ad_disclosure(marketplace_code):
        return f'{AD_DISCLOSURE_TAG}{suffix}'
    return ''


def find_blocked_copy(text: str | None) -> list[str]:
    lowered = (text or '').lower()
    return [fragment for fragment in BLOCKED_COPY_FRAGMENTS if fragment in lowered]


def assert_copy_compliant(text: str | None, marketplace_code: str | None = None) -> None:
    """Levanta ValueError se a copy contiver clickbait proibido."""
    violations = find_blocked_copy(text)
    if violations:
        raise ValueError(
            f'Copy bloqueada por clickbait proibido: {", ".join(violations)}',
        )
    if requires_ad_disclosure(marketplace_code) and AD_DISCLOSURE_TAG not in (text or '').lower():
        raise ValueError(
            f'Publicação {marketplace_code} sem disclosure obrigatório ({AD_DISCLOSURE_TAG}).',
        )
