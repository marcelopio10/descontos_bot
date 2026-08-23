from __future__ import annotations

import re
import unicodedata

"""Família editorial de produto — chave de SIMILARIDADE, não de identidade.

Motivação (achado 2026-08-21, "impressão de repetição"): o único dedup que
existia na curadoria era por `produto_canonico_id`
(apps.offers.services.normalizer.build_produto_canonico_id), que para Mercado
Livre é o ID do ANÚNCIO. Dois anúncios diferentes do mesmo tipo de produto
("Piscina Retangular Inflável ..." e "Piscina Infantil Retangular Inflável
...", ou dois power banks de 20000 mAh) têm IDs distintos e por isso nunca
colidiam — nem no lote, nem no cooldown de recorrência. Medido no banco em
2026-08-21: 28% dos envios do whatsapp_principal nos 7 dias anteriores tinham
outro envio da MESMA família nas 24h anteriores, e 26 dos 222 envios (12%)
eram tênis.

Esta chave é deliberadamente SEPARADA de `produto_canonico_id`:

- `produto_canonico_id` é identidade ("é o mesmo produto físico?") e é usada
  para DESCARTAR duplicata. Errar nela funde produtos diferentes e perde
  oferta — por isso ela continua conservadora, sem heurística de texto.
- `product_family_key` é similaridade ("é o mesmo TIPO de produto?") e é usada
  apenas para ESPAÇAR publicações no tempo e dentro do lote. Errar aqui, no
  pior caso, adia uma oferta algumas horas; nunca apaga nem funde registro.

Também é mais grossa que `Category`: categoria responde "casa_cozinha"
(73 dos 222 envios da semana), granularidade que não separa jogo de panelas de
travesseiro. A família responde "jogo_de_panelas".
"""

# `Anúncio patrocinado – ` precisa sair ANTES do dobramento de acentos: o travessão
# é não-ASCII e some no encode('ascii', 'ignore'), o que quebraria um regex que
# esperasse o separador.
SPONSORED_PREFIX_RE = re.compile(r'^\s*an[uú]ncio\s+patrocinado\s*[\-–—:]?\s*', re.IGNORECASE)

# Só procuramos o tipo de produto nas primeiras palavras do título. Títulos de
# marketplace listam o produto primeiro e enchem o resto de atributos: sem essa
# janela, "Tenda Sanfonada ... C/ Bolsa" viraria família "bolsa" e "Mochila para
# Notebook" viraria "notebook".
HEAD_WINDOW = 6

# Cabeças genéricas demais para virar família sozinhas: "Jogo de Banho" e "Jogo
# Xadrez" não são o mesmo tipo de produto. Nesses casos usamos duas palavras.
GENERIC_HEADS = frozenset({
    'jogo', 'jogos', 'kit', 'conjunto', 'combo', 'caixa', 'porta', 'suporte',
    'par', 'pack', 'aparelho', 'maquina', 'produto', 'item',
})

# Ruído de título que nunca identifica tipo de produto (cor, tamanho, público,
# adjetivo de marketing). Usado só no fallback por palavra-cabeça.
TITLE_NOISE = frozenset({
    'para', 'com', 'sem', 'nova', 'novo', 'original', 'premium', 'plus', 'super',
    'mega', 'alta', 'qualidade', 'unidades', 'pecas', 'tamanho', 'azul', 'preto',
    'preta', 'branco', 'branca', 'verde', 'vermelho', 'vermelha', 'rosa', 'cinza',
    'marrom', 'bege', 'amarelo', 'amarela', 'dourado', 'dourada', 'prata',
    'universal', 'masculino', 'masculina', 'feminino', 'feminina', 'infantil',
    'adulto', 'grande', 'pequeno', 'medio', 'tipo', 'modelo', 'unissex', 'lisa',
    'liso', 'promocao', 'oferta', 'desconto', 'frete', 'gratis',
})

# Tipos de produto reconhecidos. Frases multi-palavra ganham de palavra solta
# quando começam na mesma posição ("jogo de panelas" > "jogo"). A lista é
# propositalmente incompleta: o fallback por palavra-cabeça cobre a cauda longa,
# e um tipo novo só precisa entrar aqui quando o fallback separa indevidamente
# duas grafias do mesmo produto (foi o caso de "power bank" x "carregador
# portátil power bank", que caíam em famílias diferentes).
PRODUCT_TYPES: tuple[str, ...] = (
    # tecnologia
    'power bank', 'carregador portatil', 'bateria portatil', 'fone de ouvido',
    'fone bluetooth', 'caixa de som', 'caixa bluetooth', 'smartwatch', 'smart tv',
    'relogio inteligente', 'cabo usb', 'cartao de memoria', 'pendrive', 'roteador',
    'mouse', 'teclado', 'headset', 'monitor', 'notebook', 'tablet', 'celular',
    'capinha', 'pelicula', 'webcam', 'echo dot',
    # casa e cozinha
    'jogo de panelas', 'panela de pressao', 'panela eletrica', 'air fryer',
    'fritadeira', 'liquidificador', 'batedeira', 'cafeteira', 'sanduicheira',
    'cozedor de ovos', 'aspirador', 'jogo de cama', 'jogo de banho',
    'jogo americano', 'garrafa termica', 'copo termico', 'panela', 'frigideira',
    'travesseiro', 'edredom', 'cobertor', 'toalha', 'tapete', 'cortina',
    'mesa de cabeceira', 'mesa', 'cadeira de escritorio', 'cadeira gamer', 'luminaria',
    'lustre', 'ventilador', 'umidificador', 'ducha', 'chuveiro', 'cooktop',
    'pote hermetico', 'organizador',
    # moda e acessórios
    'camisa polo', 'camiseta', 'tenis', 'sandalia', 'chinelo', 'bota',
    'vestido', 'bermuda', 'moletom', 'jaqueta', 'pijama', 'cueca', 'sutia',
    'mochila', 'bolsa', 'mala de bordo', 'mala de viagem', 'carteira',
    # beleza
    'secador de cabelo', 'escova secadora', 'escova rotativa', 'escova alisadora',
    'chapinha', 'prancha de cabelo', 'mascara capilar', 'protetor solar',
    'perfume', 'batom', 'shampoo', 'condicionador', 'hidratante', 'depilador',
    # saúde e esporte
    'creatina', 'whey protein', 'colageno', 'multivitaminico', 'pre treino',
    'faixa elastica', 'halter', 'bicicleta ergometrica', 'esteira',
    # infantil
    'piscina inflavel', 'quebra cabeca', 'blocos de montar', 'boneca', 'boneco',
    'pelucia', 'patinete', 'triciclo', 'berco', 'carrinho de bebe', 'mamadeira',
    'piscina',
    # outros
    'soprador', 'tenda', 'gazebo', 'furadeira', 'parafusadeira', 'serra',
    'kit ferramentas', 'pneu', 'racao', 'coleira', 'arranhador', 'livro',
)

# Grafias diferentes do MESMO tipo de produto. Sem isso "Carregador Portátil
# Power Bank Turbo 20000mah" (família 'carregador_portatil') e "Power Bank
# Hardline 20000mAh" (família 'power_bank') continuariam podendo sair no mesmo
# dia — exatamente o par que o dono reportou em 2026-08-21.
TYPE_ALIASES: dict[str, str] = {
    'carregador portatil': 'power bank',
    'bateria portatil': 'power bank',
    'relogio inteligente': 'smartwatch',
    'prancha de cabelo': 'chapinha',
    'fone bluetooth': 'fone de ouvido',
    'caixa bluetooth': 'caixa de som',
    'gazebo': 'tenda',
    'fritadeira': 'air fryer',
}

# Frases longas primeiro só para acelerar a comparação de empate; a decisão real
# de qual tipo vence está em `_best_type_match`.
_SORTED_PRODUCT_TYPES: tuple[str, ...] = tuple(sorted(PRODUCT_TYPES, key=len, reverse=True))


def product_family_key(title: str, normalized_title: str = '') -> str:
    """Tipo de produto do título, ex.: 'tenis', 'power_bank', 'jogo_de_panelas'.

    Retorna string vazia quando o título não permite inferir nada — o chamador
    deve tratar família vazia como "sem restrição", nunca como uma família
    comum a todos (senão um título ilegível bloquearia todos os outros).
    """
    words = _normalize(title or normalized_title).split()
    if not words:
        return ''

    matched = _best_type_match(words[:HEAD_WINDOW])
    if matched and not _is_modifier_match(words[:HEAD_WINDOW], matched):
        return TYPE_ALIASES.get(matched, matched).replace(' ', '_')

    tokens = [
        word for word in words
        if len(word) >= 4 and word not in TITLE_NOISE and not word.isdigit()
    ]
    if not tokens:
        return ''
    if tokens[0] in GENERIC_HEADS and len(tokens) > 1:
        return f'{_singular(tokens[0])}_{_singular(tokens[1])}'
    return _singular(tokens[0])


def offer_family_key(offer) -> str:
    return product_family_key(
        getattr(offer, 'title', '') or '',
        getattr(offer, 'normalized_title', '') or '',
    )


def _singular(token: str) -> str:
    """Tira o plural simples do fallback por palavra-cabeça.

    Sem isto, "Kit 10 Cuecas Boxer" e "Cueca Boxer Kit 3" caem em famílias
    diferentes ('cuecas' e 'cueca'), e o mesmo vale para camiseta/camisetas —
    tanto no espaçamento de publicação quanto na medida de consenso entre grupos
    do radar de concorrente, que usa esta mesma chave. Só o `s` final, e só em
    palavra com corpo: "mais" e "pais" não viram "mai"/"pai".
    """
    if len(token) > 5 and token.endswith('s') and not token.endswith('ss'):
        return token[:-1]
    return token


def _best_type_match(head_words: list[str]) -> str:
    """Tipo que aparece MAIS CEDO no início do título; empate resolve pelo mais longo.

    Posição antes de comprimento é o que impede "Cadeira De Praia ... piscina"
    de virar família 'piscina' e "Mochila para Notebook" de virar 'notebook':
    o produto real é a primeira coisa que o vendedor escreve.
    """
    haystack = f' {" ".join(head_words)} '
    best_position = -1
    best_type = ''
    for candidate in _SORTED_PRODUCT_TYPES:
        position = haystack.find(f' {candidate} ')
        if position < 0:
            continue
        if best_position < 0 or position < best_position or (
            position == best_position and len(candidate) > len(best_type)
        ):
            best_position, best_type = position, candidate
    return best_type


def _is_modifier_match(head_words: list[str], matched: str) -> bool:
    """True quando o tipo casado é acessório de outro produto, não o produto.

    "Suporte Para Celular" não é um celular e "Mesa Ergonômica Para Notebook"
    não é um notebook. O sinal é uma cabeça genérica (suporte, porta, kit...)
    ANTES do tipo casado: nesse caso o tipo descreve para o que serve o item.
    Quando a cabeça genérica faz parte do próprio tipo ("jogo de panelas",
    "kit ferramentas"), ela não vem antes e a regra não dispara.
    """
    match_start = head_words.index(matched.split()[0])
    return any(
        word in GENERIC_HEADS and index < match_start
        for index, word in enumerate(head_words)
    )


def _normalize(text: str) -> str:
    without_prefix = SPONSORED_PREFIX_RE.sub('', text or '')
    decomposed = unicodedata.normalize('NFKD', without_prefix)
    ascii_text = decomposed.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', ascii_text.lower())).strip()
