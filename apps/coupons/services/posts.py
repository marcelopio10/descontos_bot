from __future__ import annotations

from html import escape

from .links import build_coupon_link


def build_coupon_post(candidate, channel) -> str:
    parts = [f'🎟️ *{candidate.marketplace}*', f'*{candidate.benefit}*']
    if candidate.activation_code:
        parts.append(f'Código: *{candidate.activation_code}*')
    if candidate.minimum_purchase:
        parts.append(f'Compra mínima: R$ {candidate.minimum_purchase:.2f}'.replace('.', ','))
    if candidate.maximum_discount:
        parts.append(f'Limite: R$ {candidate.maximum_discount:.2f}'.replace('.', ','))
    if candidate.restrictions:
        parts.append('Restrições: ' + '; '.join(candidate.restrictions))
    if candidate.valid_until:
        parts.append(f'Validade: {candidate.valid_until:%d/%m/%Y}')
    parts.append('Acesse o marketplace pelo link e aplique o cupom conforme as regras da campanha.')
    parts.append(build_coupon_link(candidate, channel))
    return '\n'.join(parts)


def build_coupon_telegram_post(candidate, channel) -> str:
    return build_coupon_post(candidate, channel)
