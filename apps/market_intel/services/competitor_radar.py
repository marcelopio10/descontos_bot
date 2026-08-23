"""Radar de concorrente — usa o observer como fonte de coleta de ofertas.

Contexto (2026-08-21). O observer captura ~4.4 mil mensagens de Mercado Livre por
semana em 14 grupos, e nada disso alimentava a coleta: era insumo só de relatório.
Ao mesmo tempo, a busca direcionada por texto no ML está bloqueada (achado B2), o
que deixou o ML entrando apenas por 8 URLs de `/ofertas?category=` — um pool de
commodity. Medido no banco na janela de 7 dias: dos produtos que o dono viu nos
grupos concorrentes, `chinelo`, `growth`, `g-shock` e `galaxy watch` tiveram
**zero** ocorrência no nosso pool e dezenas nas mensagens observadas.

Este módulo fecha esse laço em três passos separados de propósito:

1. `select_candidate_messages` escolhe mensagens que valem uma requisição.
2. `resolve_candidates` abre o link encurtado e grava o resultado em
   `ObservedOfferLink` (uma requisição por link, com pausa entre elas).
3. `build_radar_payloads` entrega ao `ScraperAdapter` o que já foi resolvido.

A separação existe para o passo 2 rodar no seu próprio timer, mais frequente que
o ciclo do bot, sem alongar a janela de coleta — e para o passo 3 ser barato e
sem rede.

Privacidade: nada que identifique grupo ou remetente entra no payload da oferta.
A proveniência que segue adiante é só `source_kind='competitor_radar'`, e
`build_sanitized_raw_payload` remove `group_jid`/`sender_hash` de qualquer forma.
"""

from __future__ import annotations

import logging
import re
import random
import time
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.db.models import Q
from django.utils import timezone

from apps.curation.services.product_family import product_family_key
from apps.curation.services.settings import (
    get_bool_setting,
    get_decimal_setting,
    get_integer_setting,
    get_json_setting,
)
from apps.distribution.models import SocialChannel
from apps.market_intel.models import ObservedOfferLink, ObservedWhatsAppMessage
from apps.market_intel.services.parser import MARKETPLACE_DOMAINS

log = logging.getLogger(__name__)

RADAR_ENABLED_FLAG = 'competitor_radar_enabled'
RADAR_LOOKBACK_HOURS = 'competitor_radar_lookback_hours'
RADAR_MAX_RESOLUTIONS = 'competitor_radar_max_resolutions'
RADAR_PAYLOAD_FRESHNESS_HOURS = 'competitor_radar_payload_freshness_hours'
RADAR_MAX_PAYLOADS = 'competitor_radar_max_payloads'
RADAR_EXCLUDED_GROUPS = 'competitor_radar_excluded_groups'
RADAR_FALLBACK_MIN_DISCOUNT = 'competitor_radar_fallback_min_discount'
RADAR_FALLBACK_MAX_PRICE = 'competitor_radar_fallback_max_price'

DEFAULT_LOOKBACK_HOURS = 12
DEFAULT_MAX_RESOLUTIONS = 40
DEFAULT_PAYLOAD_FRESHNESS_HOURS = 6
DEFAULT_MAX_PAYLOADS = 30
DEFAULT_FALLBACK_MIN_DISCOUNT = 20
DEFAULT_FALLBACK_MAX_PRICE = Decimal('700.00')

# Teto de mensagens lidas por execução para montar a fila. Precisa cobrir a
# janela inteira, e não só o que cabe no `limit`, porque o consenso entre grupos
# só aparece olhando todas as mensagens do período.
SCAN_LIMIT = 1000

# Marcadores de formatação do WhatsApp em volta da linha do produto.
_MARCADORES_WHATSAPP = '*_~`'

# O que nunca é a linha do produto: preço, cupom, CTA, rodapé de loja e convite
# de grupo. O convite entra aqui porque costuma vir em negrito e, sem ele na
# lista, ganhava do nome do produto na escolha por negrito.
_RUIDO_DE_LINHA = (
    'cupom', 'pegar promo', 'compre aqui', 'clique', 'no pix',
    'loja oficial', 'vendido por', 'frete', 'oferta no ', 'aproveite',
    'garanta', 'parcelado', 'cashback', 'menor preco', 'ver oferta', 'link na',
    'entre no nosso', 'grupo de promo', 'nosso grupo', 'participe',
)

_URL_RE = re.compile(
    r'https?://\S+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|br|la|me|to|ly|io|net)\b\S*',
    re.IGNORECASE,
)

# O preço é recortado da linha em vez de invalidá-la: em mensagem de uma linha
# só, produto e preço convivem, e rejeitar a linha inteira perdia o produto.
# O que sobra de uma linha que era só preço ("De ~R$189~ Por *R$56*") não passa
# no teste de conteúdo abaixo.
_PRECO_RE = re.compile(r'r\$\s*[\d.,]+', re.IGNORECASE)

# Palavra que ajuda a nomear produto: tem corpo e não é conectivo.
_CONECTIVOS = frozenset({'para', 'pelo', 'pela', 'como', 'esse', 'essa', 'este',
                         'esta', 'isso', 'mais', 'menos', 'ainda', 'agora', 'hoje'})

# Mesmo intervalo entre requisições que o scraper usa nas páginas de categoria.
DELAY_MIN_SECONDS = 2.0
DELAY_MAX_SECONDS = 4.5

# Só marketplaces cujo link resolve numa página que sabemos ler. Amazon
# (`amzn.to`) e Shopee (`s.shopee.com.br`) aparecem no observer mas ainda não têm
# resolvedor — entram quando houver um caminho verificado, não antes.
SUPPORTED_MARKETPLACES = ('mercadolivre',)


def radar_enabled() -> bool:
    return get_bool_setting(RADAR_ENABLED_FLAG, False)


def own_channel_group_names() -> set[str]:
    """Nomes dos grupos que são nossos — o radar nunca coleta do próprio canal.

    `SocialChannel.target` guarda o nome do grupo do WhatsApp, que é o mesmo
    nome com que o grupo chega em `ObservedWhatsAppGroup`. Ler dos canais em vez
    de manter uma lista fixa faz a exclusão acompanhar sozinha a criação de um
    canal novo.
    """
    targets = SocialChannel.objects.filter(
        channel_type__startswith='whatsapp',
    ).values_list('target', flat=True)
    return {str(target).strip() for target in targets if str(target).strip()}


def excluded_group_names() -> set[str]:
    configured = get_json_setting(RADAR_EXCLUDED_GROUPS, [])
    extra = {str(name).strip() for name in configured if str(name).strip()} if isinstance(configured, list) else set()
    return own_channel_group_names() | extra


def extract_marketplace_url(urls, marketplace_code: str) -> str:
    """Primeira URL da mensagem que pertence ao marketplace pedido."""
    domains = MARKETPLACE_DOMAINS.get(marketplace_code, ())
    for url in urls or []:
        host = (urlparse(str(url)).netloc or '').lower()
        if any(domain in host for domain in domains):
            return str(url)
    return ''


def product_line(text: str) -> str:
    """A linha da mensagem que nomeia o produto, entre headline, preço e CTA.

    As mensagens dos grupos têm forma reconhecível: manchete de efeito, nome do
    produto (quase sempre em negrito), de/por, cupom e call-to-action com link. A
    linha do produto é o que sobra depois de descartar as outras, e o negrito é o
    sinal mais confiável de qual é.

    Sem negrito, vence a mais longa entre as primeiras candidatas: manchete
    tende a ser curta e o nome do produto de marketplace, longo.
    """
    candidatas: list[tuple[bool, str]] = []
    for raw in (text or '').splitlines():
        despida = raw.strip()
        negrito = despida.startswith('*') and despida.endswith('*')
        # A URL sai da linha em vez de invalidá-la: em boa parte dos grupos a
        # mensagem é uma linha só, com emoji, link e nome do produto juntos.
        limpa = _PRECO_RE.sub(' ', _URL_RE.sub(' ', despida))
        limpa = _cortar_no_ruido(limpa)
        # Marcador e espaço saem juntos e em qualquer ordem: recortar `*R$ 899*`
        # deixa asteriscos órfãos que `.strip()` sozinho não alcança.
        limpa = re.sub(r'\s+', ' ', re.sub(rf'^[\s{re.escape(_MARCADORES_WHATSAPP)}]+|[\s{re.escape(_MARCADORES_WHATSAPP)}]+$', '', limpa))
        if len(limpa) < 8 or not _nomeia_produto(limpa):
            continue
        candidatas.append((negrito, limpa))
        if len(candidatas) >= 6:
            break

    if not candidatas:
        return ''
    for negrito, linha in candidatas:
        if negrito:
            return linha
    return max((linha for _, linha in candidatas[:4]), key=len)


def consensus_key(message: ObservedWhatsAppMessage) -> tuple[str, int] | None:
    """Chave aproximada de "mesma oferta", para medir consenso entre grupos.

    É chave de **similaridade**, nunca de identidade: serve só para ordenar a
    fila de resolução. A identidade do anúncio só existe depois de resolver o
    link, e é o `external_item_id`. Errar aqui muda a ordem da fila; não descarta
    nem funde nada.

    Usa família de produto, não marca. A primeira versão era `(marca, preço)` e
    tinha dois defeitos medidos em 2026-08-21: dependia de `BRAND_PATTERNS`, uma
    lista escrita à mão que deixava 66% das mensagens da janela sem chave — foi o
    que manteve a Insider invisível —, e quebrava o consenso quando um grupo
    escrevia a marca e o outro não, jogando dois grupos da mesma oferta em
    clusters diferentes. `product_family_key` é heurística geral, com fallback
    por palavra-cabeça, então cobre também a oferta sem marca nenhuma.

    O custo é ser mais grossa: duas camisetas diferentes na mesma faixa de preço
    caem no mesmo cluster. Como a chave só ordena, o efeito é as duas subirem
    juntas e saírem em rodadas seguidas da intercalação — o que é aceitável, e
    bem melhor que subestimar o consenso.

    Faixa de R$5 porque o mesmo produto sai com preço ligeiramente diferente
    entre grupos (R$56,00 e R$56,58 na mesma camiseta).
    """
    if not message.parsed_price:
        return None
    familia = product_family_key(product_line(message.text))
    if not familia:
        return None
    return (familia, round(float(message.parsed_price) / 5))


def select_candidate_messages(
    marketplace_code: str,
    lookback_hours: int | None = None,
    limit: int | None = None,
) -> list[tuple[ObservedWhatsAppMessage, str]]:
    """Mensagens que valem uma requisição, as de maior consenso primeiro.

    Filtra por: marketplace suportado, janela de tempo, grupo habilitado que não
    seja nosso, presença de link do marketplace e ausência de resolução anterior
    para aquele par (mensagem, url).

    A ordem importa mais do que parece. A fila tem centenas de candidatos e a
    capacidade é de algumas dezenas por execução, então ordenar por recência
    equivale a sortear. Quando dez grupos anunciam a mesma camiseta no mesmo dia
    — o caso que motivou isto, em 2026-08-21 —, esse é o sinal mais forte
    disponível de que a oferta importa, e ele estava sendo ignorado.

    Ordem final: maior número de grupos distintos anunciando, depois o que ainda
    não tem oferta equivalente resolvida na janela, depois o mais recente — e por
    fim o resultado é intercalado por cluster (ver `_interleave_by_cluster`) para
    a cota não ir toda no mesmo produto.

    O "já resolvido" entra como desempate, não como primeiro critério, e nada é
    descartado por ele. A chave de consenso é heurística: duas camisetas
    diferentes da mesma marca pelo mesmo preço caem no mesmo cluster, e foi
    exatamente o que aconteceu com a Insider (Daily T-shirt e Light T-Shirt, as
    duas a R$56). Rebaixar o cluster inteiro assim que um irmão resolve faria a
    segunda nunca sair, numa fila que drena devagar.
    """
    if marketplace_code not in SUPPORTED_MARKETPLACES:
        return []

    lookback = lookback_hours if lookback_hours is not None else get_integer_setting(
        RADAR_LOOKBACK_HOURS, DEFAULT_LOOKBACK_HOURS,
    )
    max_items = limit if limit is not None else get_integer_setting(
        RADAR_MAX_RESOLUTIONS, DEFAULT_MAX_RESOLUTIONS,
    )
    cutoff = timezone.now() - timedelta(hours=lookback)
    excluded = excluded_group_names()

    messages = list(
        ObservedWhatsAppMessage.objects
        .select_related('group')
        .filter(sent_at__gte=cutoff, parsed_marketplace=marketplace_code, group__is_enabled=True)
        .exclude(Q(urls=[]) | Q(urls__isnull=True))
        .order_by('-sent_at')[:SCAN_LIMIT]
    )

    consenso: dict[tuple[str, int], set[int]] = {}
    for message in messages:
        key = consensus_key(message)
        if key:
            consenso.setdefault(key, set()).add(message.group_id)

    ja_resolvidos = set(
        ObservedOfferLink.objects
        .filter(message__in=messages)
        .values_list('message_id', 'source_url')
    )
    clusters_resolvidos = {
        consensus_key(link.message)
        for link in ObservedOfferLink.objects
        .filter(message__in=messages, status=ObservedOfferLink.Status.RESOLVED)
        .select_related('message')
    } - {None}

    candidates: list[tuple[ObservedWhatsAppMessage, str]] = []
    seen_urls: set[str] = set()
    for message in messages:
        if message.group.name in excluded:
            continue
        url = extract_marketplace_url(message.urls, marketplace_code)
        if not url or url in seen_urls or (message.id, url) in ja_resolvidos:
            continue
        seen_urls.add(url)
        candidates.append((message, url))

    def ordem(item: tuple[ObservedWhatsAppMessage, str]):
        message = item[0]
        key = consensus_key(message)
        return (
            -len(consenso.get(key, ())) if key else -1,
            key in clusters_resolvidos,
            -message.sent_at.timestamp(),
        )

    candidates.sort(key=ordem)
    return _interleave_by_cluster(candidates)[:max_items]


def _interleave_by_cluster(
    candidates: list[tuple[ObservedWhatsAppMessage, str]],
) -> list[tuple[ObservedWhatsAppMessage, str]]:
    """Uma oferta de cada por rodada, para a cota não ir toda no mesmo produto.

    Consenso alto significa, por construção, várias mensagens equivalentes: a
    camiseta Under Armour anunciada por 4 grupos ocupava as 4 primeiras posições
    da fila e consumia 4 requisições para trazer um produto só. Intercalando, a
    primeira rodada cobre as ofertas distintas e as repetições ficam para depois.

    Nada é descartado. Cada link ainda é resolvido no máximo uma vez na vida (a
    dedup por `(mensagem, url)` garante isso), então o custo de resolver os
    irmãos de um cluster é limitado — e é o preço de não perder um produto
    diferente que só por acaso divide marca e faixa de preço com outro.
    """
    por_cluster: dict[object, list] = {}
    for index, item in enumerate(candidates):
        # Sem chave de consenso, cada candidato é o seu próprio cluster.
        key = consensus_key(item[0]) or ('__sem_chave__', index)
        por_cluster.setdefault(key, []).append(item)

    intercalado: list[tuple[ObservedWhatsAppMessage, str]] = []
    rodada = 0
    while len(intercalado) < len(candidates):
        for fila in por_cluster.values():
            if rodada < len(fila):
                intercalado.append(fila[rodada])
        rodada += 1
    return intercalado


def resolve_candidates(
    marketplace_code: str = 'mercadolivre',
    lookback_hours: int | None = None,
    limit: int | None = None,
    scraper=None,
    dry_run: bool = False,
    sleep: bool = True,
) -> dict[str, int]:
    """Abre cada link candidato e grava o anúncio correspondente.

    Uma requisição por link, com pausa entre elas. Falha de um link nunca
    interrompe o lote: vira `status=failed` com motivo, para o próximo ciclo não
    tentar de novo o mesmo link morto.
    """
    candidates = select_candidate_messages(marketplace_code, lookback_hours, limit)
    stats = {'candidates': len(candidates), 'resolved': 0, 'failed': 0, 'no_discount': 0}
    if not candidates:
        log.info('competitor_radar_sem_candidatos marketplace=%s', marketplace_code)
        return stats

    if scraper is None:
        from scrapers import mercado_livre

        scraper = mercado_livre.build_from_env()

    for index, (message, url) in enumerate(candidates):
        if getattr(scraper, 'blocked', False):
            log.warning('competitor_radar_interrompido_por_bloqueio resolvidos=%d', stats['resolved'])
            break

        payload = None
        failure = ''
        try:
            payload = scraper.scrape_social_card(url)
        except Exception as exc:  # o lote não pode cair por causa de um link
            failure = f'{type(exc).__name__}: {exc}'[:300]
            log.warning('competitor_radar_erro url=%s', url, exc_info=True)

        if payload is None and not failure:
            # `_parse_item` devolve None tanto para card ausente quanto para
            # desconto abaixo do piso do scraper. O segundo caso é o que mais
            # aparece: a oferta do concorrente costuma nascer de cupom, e sem
            # cupom o desconto de página não se sustenta sozinho.
            failure = 'sem card utilizável ou desconto de página abaixo do piso'
            stats['no_discount'] += 1

        if dry_run:
            stats['resolved' if payload else 'failed'] += 1
        else:
            _store_resolution(message, url, marketplace_code, payload, failure)
            stats['resolved' if payload else 'failed'] += 1

        if sleep and index < len(candidates) - 1:
            time.sleep(round(random.uniform(DELAY_MIN_SECONDS, DELAY_MAX_SECONDS), 2))

    log.info(
        'competitor_radar_resolucao marketplace=%s candidatos=%d resolvidos=%d falhas=%d sem_desconto=%d dry_run=%s',
        marketplace_code, stats['candidates'], stats['resolved'], stats['failed'], stats['no_discount'], dry_run,
    )
    return stats


def _store_resolution(
    message: ObservedWhatsAppMessage,
    url: str,
    marketplace_code: str,
    payload: dict | None,
    failure: str,
) -> ObservedOfferLink:
    defaults = {
        'marketplace_code': marketplace_code,
        'status': ObservedOfferLink.Status.FAILED,
        'failure_reason': failure[:300],
        'resolved_at': timezone.now(),
    }
    if payload:
        defaults.update({
            'status': ObservedOfferLink.Status.RESOLVED,
            'failure_reason': '',
            'resolved_url': str(payload.get('link_direto') or '')[:1500],
            'external_item_id': str(payload.get('id') or '')[:64],
            'title': str(payload.get('nome') or '')[:500],
            'image_url': str(payload.get('imagem') or '')[:1500],
            'seller': str(payload.get('vendedor') or '')[:200],
            'current_price': _decimal_or_none(payload.get('preco')),
            'original_price': _decimal_or_none(payload.get('preco_original')),
            'discount_pct': _decimal_or_none(payload.get('desconto_pct')),
            'affiliate_url': str(payload.get('link_afiliado') or '')[:1500],
        })
    link, _ = ObservedOfferLink.objects.update_or_create(
        message=message,
        source_url=url[:1500],
        defaults=defaults,
    )
    return link


def build_radar_payloads(
    marketplace_code: str,
    freshness_hours: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Payloads de oferta, no mesmo formato dos scrapers, a partir do resolvido.

    Só entra o que foi resolvido dentro da janela de frescor: o preço vem do card
    da vitrine no momento da resolução, e publicar preço velho é pior do que não
    publicar. Um anúncio por `external_item_id`, o mais recente.
    """
    freshness = freshness_hours if freshness_hours is not None else get_integer_setting(
        RADAR_PAYLOAD_FRESHNESS_HOURS, DEFAULT_PAYLOAD_FRESHNESS_HOURS,
    )
    max_items = limit if limit is not None else get_integer_setting(
        RADAR_MAX_PAYLOADS, DEFAULT_MAX_PAYLOADS,
    )
    cutoff = timezone.now() - timedelta(hours=freshness)

    links = (
        ObservedOfferLink.objects
        .filter(
            marketplace_code=marketplace_code,
            status=ObservedOfferLink.Status.RESOLVED,
            resolved_at__gte=cutoff,
        )
        .exclude(external_item_id='')
        .order_by('-resolved_at')
    )

    payloads: list[dict] = []
    seen_items: set[str] = set()
    dropped: dict[str, int] = {}
    for link in links:
        if len(payloads) >= max_items:
            break
        if link.external_item_id in seen_items:
            continue
        seen_items.add(link.external_item_id)

        recusa = _category_rule_violation(marketplace_code, link)
        if recusa:
            dropped[recusa] = dropped.get(recusa, 0) + 1
            continue

        payloads.append({
            'id': link.external_item_id,
            'nome': link.title,
            'preco': float(link.current_price or 0),
            'preco_original': float(link.original_price or link.current_price or 0),
            'desconto_pct': int(link.discount_pct or 0),
            'link_direto': link.resolved_url,
            'link_afiliado': link.affiliate_url,
            'imagem': link.image_url,
            'vendedor': link.seller,
            'condicao': 'Novo',
            'frete_gratis': False,
            'data': timezone.localtime(link.resolved_at).strftime('%Y-%m-%d'),
            'marketplace_code': marketplace_code,
            'search_provenance': {
                'source_kind': 'competitor_radar',
                'marketplace': marketplace_code,
            },
        })
    log.info(
        'competitor_radar_payloads marketplace=%s links=%d payloads=%d frescor_h=%d dropped=%s',
        marketplace_code, links.count(), len(payloads), freshness, dropped,
    )
    return payloads


def _category_rule_violation(marketplace_code: str, link: ObservedOfferLink) -> str:
    """Aplica ao radar as mesmas regras de categoria da coleta própria.

    Os payloads do radar não têm `category_hint` — a oferta não veio de uma URL
    de categoria, veio de um link solto. Sem isto, `_apply_category_filters` os
    deixaria passar intocados e o teto de preço da categoria (e o de exposição de
    suplementos) valeria só para metade da coleta. A categoria aqui é inferida do
    título; por isso a regra é aplicada localmente em vez de escrever
    `category_hint`, que no resto do sistema significa "veio de URL da categoria".
    """
    from apps.curation.services.classifier import classify
    from apps.offers.services.normalizer import normalize_title
    from scrapers.category_targets import get_targets

    rules = get_targets(marketplace_code).get(
        classify(
            title=link.title,
            normalized_title=normalize_title(link.title),
            source_label='',
            marketplace_code=marketplace_code,
        ).category_code
    )
    if not rules:
        # `outros`: o classifier não cobre tudo (monitor e meia caem aqui, por
        # exemplo). Na coleta por categoria isso é inofensivo, porque a URL de
        # origem já limitou o que podia entrar; no radar, o link vem solto e sem
        # piso nenhum passaria monitor de R$1.756 num canal cujo teto de
        # tecnologia é R$700. Daí um piso próprio para o que não se classifica.
        rules = {
            'min_discount': get_integer_setting(RADAR_FALLBACK_MIN_DISCOUNT, DEFAULT_FALLBACK_MIN_DISCOUNT),
            'max_price': float(get_decimal_setting(RADAR_FALLBACK_MAX_PRICE, DEFAULT_FALLBACK_MAX_PRICE)),
        }

    discount = float(link.discount_pct or 0)
    price = float(link.current_price or 0)
    if discount < rules.get('min_discount', 0):
        return 'min_discount'
    max_price = rules.get('max_price')
    if max_price is not None and price > max_price:
        return 'max_price'
    return ''


def build_coverage_report(lookback_hours: int = 24, marketplace_code: str = 'mercadolivre') -> dict:
    """O que os grupos concorrentes divulgaram e o que nós alcançamos.

    Entrega da fase 1: mede a oportunidade antes de qualquer publicação. O campo
    `sem_desconto_de_pagina` é o que justifica (ou não) tratar cupom por produto
    — é a oferta cujo valor só existe com o cupom aplicado.
    """
    from apps.offers.models import Offer

    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    excluded = excluded_group_names()

    messages = (
        ObservedWhatsAppMessage.objects
        .select_related('group')
        .filter(sent_at__gte=cutoff, parsed_marketplace=marketplace_code, group__is_enabled=True)
        .exclude(group__name__in=excluded)
    )
    total_mensagens = messages.count()
    com_cupom = messages.exclude(parsed_coupon='').count()

    links = ObservedOfferLink.objects.filter(
        marketplace_code=marketplace_code,
        created_at__gte=cutoff,
    )
    resolvidos = links.filter(status=ObservedOfferLink.Status.RESOLVED)
    itens = set(resolvidos.exclude(external_item_id='').values_list('external_item_id', flat=True))

    ja_no_pool = set(
        Offer.objects
        .filter(marketplace__code=marketplace_code, external_id__in=itens)
        .values_list('external_id', flat=True)
    ) if itens else set()

    return {
        'janela_horas': lookback_hours,
        'marketplace': marketplace_code,
        'mensagens_observadas': total_mensagens,
        'mensagens_com_cupom': com_cupom,
        'links_tentados': links.count(),
        'links_resolvidos': resolvidos.count(),
        'sem_desconto_de_pagina': links.filter(
            status=ObservedOfferLink.Status.FAILED,
            failure_reason__icontains='desconto de página',
        ).count(),
        'anuncios_distintos': len(itens),
        'ja_no_nosso_pool': len(ja_no_pool),
        'inedito_para_nos': len(itens - ja_no_pool),
    }


def _cortar_no_ruido(linha: str) -> str:
    """Trunca a linha no primeiro marcador de cupom/CTA/rodapé.

    Rejeitar a linha inteira por conter ruído funcionava enquanto a mensagem era
    multi-linha. Boa parte dos grupos manda tudo numa linha só — emoji, link,
    produto, preço e cupom —, e ali o ruído vem **depois** do produto: descartar
    perdia a mensagem inteira. Truncando, a linha que era só cupom encolhe até
    não passar no teste de conteúdo, e a que tinha produto sobrevive.
    """
    folded, indices = _fold_com_indices(linha)
    corte = min(
        (folded.find(ruido) for ruido in _RUIDO_DE_LINHA if folded.find(ruido) >= 0),
        default=-1,
    )
    return linha if corte < 0 else linha[: indices[corte]]


def _fold_com_indices(text: str) -> tuple[str, list[int]]:
    """Versão sem acento e em minúsculas, com o índice original de cada caractere.

    O mapa de índices existe porque dobrar acento muda o comprimento da string
    ("ç" vira "c" mais um combinante que é removido), então a posição achada no
    texto dobrado não serve para cortar o original.
    """
    folded: list[str] = []
    indices: list[int] = []
    for posicao, caractere in enumerate(text or ''):
        for parte in unicodedata.normalize('NFKD', caractere):
            if unicodedata.combining(parte):
                continue
            folded.append(parte.lower())
            indices.append(posicao)
    return ''.join(folded), indices


def _nomeia_produto(linha: str) -> bool:
    """Duas palavras com corpo — o que sobra de linha de preço não passa aqui."""
    palavras = [
        palavra for palavra in re.findall(r'[a-zà-ÿ]{4,}', _fold(linha))
        if palavra not in _CONECTIVOS
    ]
    return len(palavras) >= 2


def _fold(text: str) -> str:
    decomposto = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposto if not unicodedata.combining(c)).lower()


def _decimal_or_none(value) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
