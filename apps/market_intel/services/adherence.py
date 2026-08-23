"""Aderência dos nossos envios ao que os grupos concorrentes publicam.

Responde três perguntas que o relatório de market intel não respondia, porque ele
mede cobertura do **catálogo** (o que conseguimos coletar) e não do que de fato
foi **enviado** ao canal:

1. Do que publicamos, quanto os grupos também estavam publicando?
2. Do que os grupos empurram com força (várias fontes na mesma oferta), quanto
   chegou ao nosso canal?
3. Quando publicamos a mesma oferta, quanto tempo depois deles?

O casamento usa a mesma chave de similaridade do radar — família de produto mais
faixa de preço — em vez de sobreposição de tokens de título. É mais robusto
porque o texto do grupo é copy de marketing ("60 CONTO NA PEITA DA UNDER"),
não título de anúncio, e os dois raramente compartilham tokens suficientes.

Como toda chave de similaridade neste projeto, ela só mede e ordena: nada aqui
descarta, funde ou bloqueia oferta.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from apps.curation.services.product_family import product_family_key
from apps.distribution.models import Delivery
from apps.market_intel.models import ObservedWhatsAppMessage
from apps.market_intel.services.competitor_radar import (
    consensus_key,
    excluded_group_names,
    product_line,
)

# Uma oferta que eles publicaram até 3 dias antes ainda é "a mesma onda" que a
# nossa: campanha de cupom do ML costuma durar alguns dias. Depois do nosso
# envio a janela é curta, só para não perder o caso de sairmos primeiro.
JANELA_ANTES_HORAS = 72
JANELA_DEPOIS_HORAS = 12

# A partir de quantos grupos distintos uma oferta conta como "empurrada com
# força" — o mesmo limiar que faz o radar priorizar resolução.
CONSENSO_FORTE = 3


@dataclass
class Adherence:
    janela_dias: int
    canal: str
    envios: int = 0
    mensagens_observadas: int = 0
    envios_com_eco: int = 0
    envios_com_eco_de_familia: int = 0
    envios_exclusivos: int = 0
    lags_horas: list[float] = field(default_factory=list)
    ofertas_consenso_forte: int = 0
    consenso_forte_publicado: int = 0
    lacunas: list[dict] = field(default_factory=list)
    exclusivos: list[dict] = field(default_factory=list)
    por_origem: dict = field(default_factory=dict)

    @property
    def taxa_eco(self) -> float:
        return round(100 * self.envios_com_eco / self.envios, 1) if self.envios else 0.0

    @property
    def taxa_eco_de_familia(self) -> float:
        """Teto do intervalo: mesmo TIPO de produto, sem exigir a mesma faixa de preço.

        O piso (`taxa_eco`) subestima de forma sistemática, porque os grupos
        anunciam o preço já com cupom e nós o preço de página — a mesma oferta
        cai em faixas diferentes. Este número superestima, porque família é
        grossa: duas camisetas quaisquer casam. A verdade fica entre os dois.
        """
        return round(100 * self.envios_com_eco_de_familia / self.envios, 1) if self.envios else 0.0

    @property
    def taxa_cobertura_consenso(self) -> float:
        if not self.ofertas_consenso_forte:
            return 0.0
        return round(100 * self.consenso_forte_publicado / self.ofertas_consenso_forte, 1)

    @property
    def lag_mediano(self) -> float | None:
        return round(statistics.median(self.lags_horas), 1) if self.lags_horas else None

    def as_dict(self) -> dict:
        return {
            'janela_dias': self.janela_dias,
            'canal': self.canal,
            'envios': self.envios,
            'mensagens_observadas': self.mensagens_observadas,
            'envios_com_eco_nos_grupos': self.envios_com_eco,
            'taxa_de_eco_pct': self.taxa_eco,
            'taxa_de_eco_por_familia_pct': self.taxa_eco_de_familia,
            'envios_exclusivos': self.envios_exclusivos,
            'lag_mediano_horas': self.lag_mediano,
            'ofertas_com_consenso_forte': self.ofertas_consenso_forte,
            'consenso_forte_publicado': self.consenso_forte_publicado,
            'cobertura_do_consenso_pct': self.taxa_cobertura_consenso,
            'por_origem': self.por_origem,
            'maiores_lacunas': self.lacunas,
            'amostra_de_exclusivos': self.exclusivos,
        }


def radar_latency(channel_code: str = 'whatsapp_principal') -> dict:
    """Latência exata do radar: mensagem do grupo → nosso envio.

    Aqui o par é exato, não aproximado: `ObservedOfferLink` liga a mensagem que
    originou o link ao anúncio resolvido, então é o mesmo produto por construção.
    Por isso este número vale mais que o atraso por origem calculado em
    `build_adherence`, que compara com a mensagem mais antiga da janela e satura
    em campanha longa.

    Só conta envio **posterior** à resolução. Anúncio que já tinha saído antes
    não foi puxado pelo radar, e contá-lo daria latência negativa.
    """
    from apps.market_intel.models import ObservedOfferLink
    from apps.offers.models import Offer

    ate_publicar: list[float] = []
    ate_resolver: list[float] = []
    ja_publicados = 0

    links = (
        ObservedOfferLink.objects
        .filter(status=ObservedOfferLink.Status.RESOLVED)
        .exclude(external_item_id='')
        .select_related('message')
    )
    for link in links:
        oferta = Offer.objects.filter(
            marketplace__code=link.marketplace_code,
            external_id=link.external_item_id,
        ).first()
        if not oferta:
            continue
        entrega = (
            Delivery.objects
            .filter(
                offer=oferta,
                delivery_status=Delivery.DeliveryStatus.SENT,
                social_channel__code=channel_code,
                sent_at__gte=link.resolved_at,
            )
            .order_by('sent_at')
            .first()
        )
        if not entrega:
            if Delivery.objects.filter(offer=oferta, delivery_status=Delivery.DeliveryStatus.SENT).exists():
                ja_publicados += 1
            continue
        ate_publicar.append((entrega.sent_at - link.message.sent_at).total_seconds() / 3600)
        ate_resolver.append((link.resolved_at - link.message.sent_at).total_seconds() / 3600)

    return {
        'publicados_pelo_radar': len(ate_publicar),
        'ja_estavam_no_canal': ja_publicados,
        'latencia_mediana_horas': round(statistics.median(ate_publicar), 1) if ate_publicar else None,
        'latencia_minima_horas': round(min(ate_publicar), 1) if ate_publicar else None,
        'latencia_maxima_horas': round(max(ate_publicar), 1) if ate_publicar else None,
        'ate_resolver_mediana_horas': round(statistics.median(ate_resolver), 1) if ate_resolver else None,
    }


def _offer_key(offer) -> tuple[str, int] | None:
    if not offer or offer.current_price is None:
        return None
    familia = product_family_key(offer.title or '', offer.normalized_title or '')
    if not familia:
        return None
    return (familia, round(float(offer.current_price) / 5))


def _origem(offer) -> str:
    return (offer.raw_payload or {}).get('search_provenance', {}).get('source_kind') or 'desconhecida'


def build_adherence(days: int = 7, channel_code: str = 'whatsapp_principal') -> Adherence:
    inicio = timezone.now() - timedelta(days=days)
    resultado = Adherence(janela_dias=days, canal=channel_code)

    # Índice do que os grupos publicaram: chave -> ocorrências (quando, qual grupo).
    # A janela é alargada para trás para achar o eco de um envio feito no começo
    # do período.
    observadas = (
        ObservedWhatsAppMessage.objects
        .select_related('group')
        .filter(sent_at__gte=inicio - timedelta(hours=JANELA_ANTES_HORAS), group__is_enabled=True)
        .exclude(group__name__in=excluded_group_names())
    )
    indice: dict[tuple[str, int], list[tuple]] = defaultdict(list)
    por_familia: dict[str, list[tuple]] = defaultdict(list)
    grupos_por_chave: dict[tuple[str, int], set[int]] = defaultdict(set)
    for mensagem in observadas:
        chave = consensus_key(mensagem)
        if not chave:
            continue
        indice[chave].append((mensagem.sent_at, mensagem.group_id, mensagem))
        por_familia[chave[0]].append((mensagem.sent_at, mensagem.parsed_price))
        if mensagem.sent_at >= inicio:
            grupos_por_chave[chave].add(mensagem.group_id)
    resultado.mensagens_observadas = sum(
        1 for m in observadas if m.sent_at >= inicio
    )

    entregas = (
        Delivery.objects
        .select_related('offer')
        .filter(
            social_channel__code=channel_code,
            delivery_status=Delivery.DeliveryStatus.SENT,
            sent_at__gte=inicio,
        )
    )

    publicadas: set[tuple[str, int]] = set()
    origem_eco: Counter = Counter()
    origem_total: Counter = Counter()
    lags_por_origem: dict[str, list[float]] = defaultdict(list)
    for entrega in entregas:
        resultado.envios += 1
        chave = _offer_key(entrega.offer)
        origem = _origem(entrega.offer)
        origem_total[origem] += 1
        if chave:
            publicadas.add(chave)

        ecos = [
            quando for quando, _, _ in indice.get(chave, ())
            if entrega.sent_at - timedelta(hours=JANELA_ANTES_HORAS)
            <= quando
            <= entrega.sent_at + timedelta(hours=JANELA_DEPOIS_HORAS)
        ] if chave else []

        # Mesmo tipo de produto, sem exigir a mesma faixa de preço — o teto do
        # intervalo. Comparar preço aqui não vale: dentro de uma família cabem
        # produtos muito diferentes (um tênis de R$99 e um de R$359), então a
        # diferença mediria variedade de catálogo, não desvantagem de preço. O
        # efeito do cupom está medido no radar, onde o par é o mesmo anúncio.
        if chave and any(
            entrega.sent_at - timedelta(hours=JANELA_ANTES_HORAS)
            <= quando
            <= entrega.sent_at + timedelta(hours=JANELA_DEPOIS_HORAS)
            for quando, _ in por_familia.get(chave[0], ())
        ):
            resultado.envios_com_eco_de_familia += 1

        if ecos:
            resultado.envios_com_eco += 1
            origem_eco[origem] += 1
            atraso = round((entrega.sent_at - min(ecos)).total_seconds() / 3600, 1)
            resultado.lags_horas.append(atraso)
            lags_por_origem[origem].append(atraso)
        else:
            resultado.envios_exclusivos += 1
            if len(resultado.exclusivos) < 15:
                resultado.exclusivos.append({
                    'titulo': (entrega.offer.title or '')[:70],
                    'preco': float(entrega.offer.current_price or 0),
                    'familia': chave[0] if chave else '(sem familia)',
                    'origem': origem,
                })

    resultado.por_origem = {
        origem: {
            'envios': total,
            'com_eco': origem_eco.get(origem, 0),
            'taxa_de_eco_pct': round(100 * origem_eco.get(origem, 0) / total, 1) if total else 0.0,
            'lag_mediano_horas': (
                round(statistics.median(lags_por_origem[origem]), 1)
                if lags_por_origem.get(origem) else None
            ),
        }
        for origem, total in origem_total.most_common()
    }

    # Cobertura do consenso: das ofertas que vários grupos empurraram, quantas
    # saíram no nosso canal.
    fortes = {chave: grupos for chave, grupos in grupos_por_chave.items() if len(grupos) >= CONSENSO_FORTE}
    resultado.ofertas_consenso_forte = len(fortes)
    resultado.consenso_forte_publicado = sum(1 for chave in fortes if chave in publicadas)

    lacunas = sorted(
        ((chave, grupos) for chave, grupos in fortes.items() if chave not in publicadas),
        key=lambda item: -len(item[1]),
    )[:15]
    resultado.lacunas = [
        {
            'familia': chave[0],
            'faixa_preco': f'~R$ {chave[1] * 5}',
            'grupos': len(grupos),
            'exemplo': next(
                (product_line(m.text)[:60] for _, _, m in indice[chave] if product_line(m.text)),
                '',
            ),
        }
        for chave, grupos in lacunas
    ]
    return resultado
