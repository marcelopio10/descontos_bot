from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from django.core.serializers.json import DjangoJSONEncoder

from apps.curation.services.ai_schema import OUTPUT_SCHEMA_VERSION


class HermesRunnerError(RuntimeError):
    """Raised when a Hermes curation run cannot produce a usable payload."""


class HermesRunner(Protocol):
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return structured JSON for the curation payload."""
        ...


@dataclass(frozen=True)
class HermesProfileRunner:
    """Calls the real Hermes CLI profile and extracts a JSON curation payload."""

    profile_name: str = 'descontos-bot'
    timeout_seconds: int = 180
    hermes_binary: str = 'hermes'

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = build_curation_prompt(payload)
        command = [self.hermes_binary, '-p', self.profile_name, 'chat', '-Q', '-q', prompt]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HermesRunnerError(f'Hermes CLI excedeu timeout de {self.timeout_seconds}s') from exc
        except OSError as exc:
            raise HermesRunnerError(f'Hermes CLI indisponível: {exc}') from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip()[:1000]
            if any(kw in detail.lower() for kw in ('session', 'auth', 'login', 'expired')):
                raise HermesRunnerError(
                    f'Hermes CLI falhou com código {completed.returncode} (sessão/autenticação inválida): '
                    f'renove a autenticação do profile "{self.profile_name}" e tente novamente. Detalhe: {detail}'
                )
            raise HermesRunnerError(f'Hermes CLI falhou com código {completed.returncode}: {detail}')
        return extract_json_payload((completed.stdout or '') + '\n' + (completed.stderr or ''))


def build_curation_prompt(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True)
    return (
        'Você é o profile Hermes de curadoria IA do descontos.bot. '\
        'Responda SOMENTE JSON puro, sem markdown, sem comentários e sem texto extra.\n'
        f'O JSON de saída deve ter schema_version "{OUTPUT_SCHEMA_VERSION}", actual_distribution e decisions.\n'
        'Cada item em decisions DEVE conter exatamente estes campos compatíveis com o validador: '
        'offer_id, marketplace_code, classification, selected_for_batch, batch_position, '
        'conversion_score, relevance_score, discount_quality_score, audience_fit_score, reason, '
        'rewritten_title, rewritten_caption_whatsapp, rewritten_caption_telegram, image_required, '
        'image_decision, blacklist_actions, risk_flags.\n'
        'classification deve ser approved, rejected ou improper. '\
        'Itens improper, com risk_flags adult_content/weapon/obscene ou image_decision improper/adult_content/obscene/blocked nunca podem ser selected_for_batch=true. '\
        'Use batch_position inteiro positivo somente para selecionados; use null para não selecionados.\n'
        'Respeite a composição alvo sempre que houver candidatas seguras: 40% Mercado Livre, 30% Amazon e 30% Shopee. '
        'Se houver poucas candidatas seguras de um marketplace, selecione o máximo viável dele antes de redistribuir os slots. '
        'Não deixe Shopee zerada quando existirem ofertas Shopee aprováveis; em lote pequeno, priorize ao menos 1 Shopee segura. '
        'Ofertas com editorial_flags contendo low_priority_book representam livros; livros têm baixa conversão e só devem entrar como preenchimento quando faltarem opções melhores.\n'
        'Nas captions reescritas, escreva como uma pessoa real de grupo de ofertas, não como chatbot. '
        'Aplique os princípios da skill humanizer: corte frases com cara de IA, varie ritmo e estrutura, prefira linguagem simples e específica, e evite tom formal/promocional. '
        'Não use fórmulas repetidas entre ofertas, principalmente começos iguais como "Boa para", "Vale para", "Oferta para", "Quem procura" ou "Se você". '
        'Alterne naturalmente o ponto de entrada: às vezes destaque preço, às vezes uso prático, marca, urgência leve, presente, reposição ou comparação com preço normal. '
        'Evite repetir título, preço, percentual de desconto, marketplace ou CTA; esses dados já aparecem no template final. '
        'Não use labels internos, markdown, emojis decorativos, hashtags, "Trecho do agente", "curadoria" ou frases com cara de assistente. '
        'Cada rewritten_caption_* deve ter 1 frase curta, natural e diferente das demais, com no máximo 140 caracteres.\n'
        'Payload de entrada:\n'
        f'{serialized}'
    )


def extract_json_payload(text: str) -> dict[str, Any]:
    for candidate in reversed(_json_object_candidates(text)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise HermesRunnerError('Hermes não retornou JSON objeto válido')


def _json_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    starts: list[int] = []
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            starts.append(index)
        elif char == '}' and starts:
            start = starts.pop()
            if not starts:
                candidates.append(text[start:index + 1])
    return candidates


@dataclass
class FakeHermesRunner:
    """Deterministic Sprint-4 runner used before real Hermes integration.

    It deliberately does not call Hermes, external APIs or delivery services. The
    real profile runner is introduced later; this fake exercises the orchestration,
    schema validation and persistence path safely.
    """

    should_fail: bool = False
    forced_payload: dict[str, Any] | None = None

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.should_fail:
            raise HermesRunnerError('falha simulada do Hermes')
        if self.forced_payload is not None:
            return self.forced_payload

        offers = list(payload.get('offers') or [])
        batch_size = int((payload.get('run') or {}).get('batch_size') or len(offers))

        # Deterministic top-N selection by score descending
        scored = sorted(offers, key=lambda o: -_score_from_offer(o))
        selected_offer_ids = {o.get('offer_id') for o in scored[:batch_size]}
        offer_to_position = {o.get('offer_id'): pos for pos, o in enumerate(scored[:batch_size], start=1)}

        decisions: list[dict[str, Any]] = []
        for offer in offers:
            score = _score_from_offer(offer)
            offer_id = offer.get('offer_id')
            title = str(offer.get('title') or '').strip() or f'Oferta {offer_id}'
            marketplace_code = str(offer.get('marketplace_code') or '').strip()
            is_selected = offer_id in selected_offer_ids
            decisions.append(
                {
                    'offer_id': offer_id,
                    'marketplace_code': marketplace_code,
                    'classification': 'approved',
                    'selected_for_batch': is_selected,
                    'batch_position': offer_to_position.get(offer_id) if is_selected else None,
                    'conversion_score': score,
                    'relevance_score': score,
                    'discount_quality_score': score,
                    'audience_fit_score': score,
                    'reason': 'Aprovada pelo runner mockado para validar a orquestração.',
                    'rewritten_title': title[:500],
                    'rewritten_caption_whatsapp': f'{title} — oferta selecionada com curadoria.',
                    'rewritten_caption_telegram': f'{title} — oferta selecionada com curadoria.',
                    'image_required': False,
                    'image_decision': 'skip',
                    'blacklist_actions': [],
                    'risk_flags': [],
                }
            )
        return {
            'schema_version': OUTPUT_SCHEMA_VERSION,
            'decisions': decisions,
            'actual_distribution': {},
        }


def _score_from_offer(offer: dict[str, Any]) -> float:
    baseline_value = offer.get('baseline')
    baseline = baseline_value if isinstance(baseline_value, dict) else {}
    score = baseline.get('score')
    if score is None:
        score = offer.get('discount_pct') or 0
    return round(float(score), 2)
