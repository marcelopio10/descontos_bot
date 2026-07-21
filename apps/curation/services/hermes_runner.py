from __future__ import annotations

import json
import os
import re
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
    """Calls the real Hermes CLI profile and extracts a JSON curation payload.

    Passes the prompt via -q (query flag) for clean stdout output.
    """

    profile_name: str = 'descontos-bot'
    # Tarefa 5.4 (achado E): default alinhado a AI_CURATION_RUNNER_TIMEOUT em run_bot.py
    # (dados que embasam o valor estão documentados lá). Na prática, o único call site de
    # produção (prepare_ai_curation_batch.py) sempre passa timeout_seconds explicitamente;
    # este default só protege chamadas diretas/futuras que não especifiquem o valor.
    timeout_seconds: int = 450
    hermes_binary: str = 'hermes'
    model_override: str | None = None
    provider_override: str | None = None

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = build_curation_prompt(payload)
        env = {**os.environ}
        command = [self.hermes_binary, 'chat', '-Q', '--profile', self.profile_name]
        if self.model_override:
            command += ['-m', self.model_override]
        if self.provider_override:
            command += ['--provider', self.provider_override]
        command += ['-q', prompt]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
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
        payload = extract_json_payload((completed.stdout or '') + '\n' + (completed.stderr or ''))
        return sanitize_hermes_payload(payload)


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


# Tarefa 5.3 (achado P9): CLIs de LLM ocasionalmente vazam texto de "raciocínio"
# interno (chain-of-thought) dentro dos próprios campos de texto livre do JSON de
# saída — tags <think>/<reasoning>, prefixos de monólogo ("Let me think...",
# "Okay, thinking about this...") ou blocos de código markdown (```...```) que
# sobraram de uma resposta mal formatada. Isso nunca deve chegar ao título/caption
# publicados. `sanitize_ai_text` é aplicada nos campos de texto livre retornados
# pelo Hermes ANTES de eles virarem `CurationDecision.title_rewritten`/
# `caption_rewritten` (ver `sanitize_hermes_payload`, chamada em
# `HermesProfileRunner.run()` logo após extrair o JSON).
_THINK_BLOCK_RE = re.compile(
    r'<\s*(?:think|thinking|reasoning|scratchpad|analysis)\b[^>]*>.*?<\s*/\s*(?:think|thinking|reasoning|scratchpad|analysis)\s*>',
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_THINK_TAG_RE = re.compile(
    r'<\s*(?:think|thinking|reasoning|scratchpad|analysis)\b[^>]*>.*',
    re.IGNORECASE | re.DOTALL,
)
# Gatilhos deliberadamente ESPECÍFICOS (frases de raciocínio conhecidas, não palavras
# soltas tipo "so"/"ok" isoladas) para não confundir uma legenda normal com vazamento.
# O terminador inclui vírgula além de ponto/dois-pontos/quebra de linha: sem isso, um
# vazamento como "Okay, thinking about this, <legenda real aqui>." consumiria a
# legenda real inteira (só pararia no PRÓXIMO ponto final, que é o da legenda).
_REASONING_PREFIX_RE = re.compile(
    r'^\s*(?:'
    r"let'?s think[^.\n:,]*[.\n:,]+|"
    r'let me think[^.\n:,]*[.\n:,]+|'
    r'i need to (?:think|analyze|figure out|consider)[^.\n:,]*[.\n:,]+|'
    r'(?:okay|ok|alright),?\s+(?:let me|thinking)[^.\n:,]*[.\n:,]+|'
    r'thinking about this[^.\n:,]*[.\n:,]+|'
    r'first,?\s+(?:let me|i need to)[^.\n:,]*[.\n:,]+|'
    r'vamos pensar[^.\n:,]*[.\n:,]+|'
    r'deixa(?:-me| eu)? pensar[^.\n:,]*[.\n:,]+|'
    r'pensando (?:nisso|sobre isso)[^.\n:,]*[.\n:,]+'
    r')\s*',
    re.IGNORECASE,
)
# A tag de linguagem só é consumida junto com a cerca de abertura quando vem
# seguida de quebra de linha (formato usual ```lang\n...); caso contrário só os
# 3 backticks são removidos, para não engolir uma palavra legítima colada neles.
_CODE_FENCE_RE = re.compile(r'```[a-zA-Z0-9_+-]*\n|```')

_HERMES_TEXT_FIELDS = ('rewritten_title', 'rewritten_caption_whatsapp', 'rewritten_caption_telegram')


def sanitize_ai_text(raw: str | None) -> str:
    """Remove vazamento de raciocínio/formatação indevida de texto livre da IA.

    Cobre: blocos `<think>`/`<reasoning>`/`<thinking>`/`<scratchpad>`/`<analysis>`
    (fechados ou não — se a tag nunca fechar, tudo depois dela é descartado, pois
    nesse caso o campo inteiro costuma ser só o raciocínio vazado), prefixos de
    monólogo tipo "Let me think..."/"Okay, thinking about this..." (removidos
    repetidamente, caso o modelo encadeie mais de um), e cercas de código markdown
    (```...```) perdidas no meio do texto final.
    """
    if not raw:
        return ''
    text = raw
    text = _THINK_BLOCK_RE.sub(' ', text)
    text = _UNCLOSED_THINK_TAG_RE.sub(' ', text)
    previous = None
    while previous != text:
        previous = text
        text = _REASONING_PREFIX_RE.sub('', text)
    text = _CODE_FENCE_RE.sub('', text)
    return ' '.join(text.split()).strip()


def sanitize_hermes_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Aplica `sanitize_ai_text` nos campos de texto livre de cada decisão do payload.

    Muta e retorna o próprio `payload` (dict recém-parseado do JSON do Hermes,
    sem outros donos), evitando uma cópia profunda desnecessária.
    """
    decisions = payload.get('decisions')
    if isinstance(decisions, list):
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            for field in _HERMES_TEXT_FIELDS:
                value = decision.get(field)
                if isinstance(value, str):
                    decision[field] = sanitize_ai_text(value)
    return payload


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
