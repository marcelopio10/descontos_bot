"""Configuração declarativa de scraping orientado a categorias (Sprint 5).

Cada entrada cobre uma das categorias prioritárias para o público real
(DF, 35+, familiar). O scraper genérico (scrape_daily_deals) continua
disponível como fallback — Sprint 5 acrescenta caminho complementar
sem remover o atual.

Estrutura:
    {
        marketplace_code: {
            category_code: {
                'urls':           [(rotulo, url_ou_product_cat_id), ...],
                'priority_brands': (str, ...),     # informativo (consumido pelo score)
                'min_discount':    int,            # filtro pós-extração
                'max_price':       float | None,
                'cycle_limit':     int,            # corte por categoria/ciclo
                'fallback':        'generic' | 'skip',
            }
        }
    }

Revisão dos tetos de `max_price` — 2026-08-23
---------------------------------------------
Os tetos passaram a ser calibrados pela **taxa de comissão medida** no painel de
afiliados do ML (74 vendas, mai–ago/2026), e não pela intuição de "preço que o
público paga". O gatilho foi o achado de que 45,3% da comissão de cliente de maio
veio de vendas acima de R$ 500 e que essa faixa zerou a partir de junho.

Efeito medido dos tetos anteriores no preço máximo de oferta de ML coletada
(maio → agosto), que confirma quais deles estavam mordendo:

    beleza_cuidados       R$ 819  → R$ 299   (teto 300 — cortou o perfume de R$ 717
                                              que rendeu R$ 94,16 a 16% em maio)
    infantil              R$ 1549 → R$ 399   (teto 400)
    casa_cozinha          R$ 5299 → R$ 642   (teto 600)
    tecnologia_cotidiana  R$ 3899 → R$ 2099  (teto 700, vaza por alvo sem hint)

Taxa de comissão observada, que define para onde cada teto vai:

    ALTA  (12–26%)  perfumaria/beleza 16–17% · moda 16–26% · cozinha 17%
                    fitness/musculação 16% · equipamento médico 12%
    BAIXA (2,5–7%)  celulares 5% · áudio 5% · acessórios 5% · relógios 6%
                    pequenos eletrodomésticos 6,8% · colecionáveis 6%

Daí a assimetria: beleza e casa sobem, moda sobe um degrau, e
`tecnologia_cotidiana` **desce** — era o teto mais alto do arquivo servindo à
categoria que menos paga. `saude_suplementacao` fica intocada de propósito: o
teto baixo ali não é comercial, é exposição limitada por viés do dono (~80% das
vendas de suplemento registradas são compra dele).

Importante para quem for medir o efeito: alvos com `trust_hint=False` (ML
MLB1430 e MLB1276) **não passam por este filtro** — sem `category_hint` no
payload, `_apply_category_filters` deixa passar. Bicicleta ergométrica e o resto
de Esportes entram por ali, classificados como `outros`, sem teto nenhum.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryTarget:
    marketplace: str
    category_code: str
    label: str
    url: str | int
    trust_hint: bool = True


CATEGORY_TARGETS: dict[str, dict[str, dict]] = {
    'amazon': {
        'casa_cozinha': {
            'urls': [
                ('Casa e Cozinha', 'https://www.amazon.com.br/s?k=casa&i=kitchen&deal-type=eligible'),
                ('Cozinha Utensílios', 'https://www.amazon.com.br/s?k=utensilios+cozinha&i=kitchen&deal-type=eligible'),
            ],
            'priority_brands': ('tramontina', 'oster', 'mondial', 'arno', 'philips walita', 'electrolux'),
            'min_discount': 15,
            'max_price': 800.0,  # 600 → 800 (2026-08-23): cozinha paga 16,8%
            'cycle_limit': 25,
            'fallback': 'generic',
        },
        'moda_feminina': {
            'urls': [
                ('Moda Feminina', 'https://www.amazon.com.br/s?k=moda+feminina&i=apparel&deal-type=eligible'),
                ('Calçados Femininos', 'https://www.amazon.com.br/s?k=tenis+feminino&i=shoes&deal-type=eligible'),
            ],
            'priority_brands': ('nike', 'adidas', 'mizuno', 'olympikus', 'havaianas', 'colcci'),
            'min_discount': 20,
            'max_price': 600.0,  # 500 → 600 (2026-08-23): moda paga 16–26%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'moda_masculina': {
            'urls': [
                ('Moda Masculina', 'https://www.amazon.com.br/s?k=camiseta+masculina&i=apparel&deal-type=eligible'),
                ('Calçados Masculinos', 'https://www.amazon.com.br/s?k=tenis+masculino&i=shoes&deal-type=eligible'),
            ],
            'priority_brands': ('insider', 'nike', 'adidas', 'puma', 'fila', 'mizuno', 'asics', 'new balance', 'under armour', 'oakley', 'vans', 'converse', 'calvin klein', 'tommy hilfiger'),
            'min_discount': 15,
            'max_price': 600.0,  # 500 → 600 (2026-08-23): moda paga 16–26%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'infantil': {
            'urls': [
                ('Brinquedos', 'https://www.amazon.com.br/s?k=brinquedos&i=toys&deal-type=eligible'),
                ('Infantil', 'https://www.amazon.com.br/s?k=produtos+bebe&i=baby&deal-type=eligible'),
            ],
            'priority_brands': ('mattel', 'hasbro', 'lego', 'fisher-price', 'estrela'),
            'min_discount': 15,
            'max_price': 500.0,  # 400 → 500 (2026-08-23): brinquedo paga 11–16%, colecionável só 6%
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'tecnologia_cotidiana': {
            'urls': [
                ('Eletrônicos', 'https://www.amazon.com.br/s?i=aps&deal-type=eligible&rh=n%3A1229514011'),
                ('Acessórios Celular', 'https://www.amazon.com.br/s?k=carregador+celular&deal-type=eligible'),
            ],
            'priority_brands': ('samsung', 'xiaomi', 'jbl', 'sony', 'logitech', 'tcl', 'lg'),
            'min_discount': 15,
            'max_price': 500.0,  # 800 → 500 (2026-08-23): era o teto mais alto do arquivo servindo a 2,5–6,8% de comissão
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'beleza_cuidados': {
            'urls': [
                ('Beleza', 'https://www.amazon.com.br/s?k=beleza&i=beauty&deal-type=eligible'),
                ('Cuidados Pessoais', 'https://www.amazon.com.br/s?k=skincare&i=beauty&deal-type=eligible'),
            ],
            'priority_brands': ('avon', 'natura', 'eudora', 'o boticario', 'loreal', 'elseve', 'oral-b', 'colgate', 'taiff', 'kerastase'),
            'min_discount': 20,
            'max_price': 800.0,  # 400 → 800 (2026-08-23): perfumaria paga 16% com ticket de R$ 416
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'saude_suplementacao': {
            'urls': [
                ('Saúde — Suplementos', 'https://www.amazon.com.br/s?k=suplemento&i=hpc&deal-type=eligible'),
            ],
            'priority_brands': ('growth', 'max titanium', 'dark lab', 'integralmedica', 'vitafor', 'dux nutrition', 'adaptogen', 'soldiers nutrition', 'atlhetica nutrition', 'bodyaction', 'probiótica', 'essential nutrition', 'nutrify', 'optimum nutrition', 'universal nutrition', 'muscletech', 'black skull'),
            'min_discount': 25,
            'max_price': 300.0,
            'cycle_limit': 5,  # exposição limitada — viés do dono
            'fallback': 'skip',
        },
    },
    'mercadolivre': {
        # As URLs `lista.mercadolivre.com.br/<slug>/_DiscountRange_...` foram
        # bloqueadas pelo anti-bot (Akamai Bot Manager) com um proof-of-work
        # SHA-256 em JS — requests puro recebe micro-landing vazia. Apenas
        # `www.mercadolivre.com.br/ofertas?category=MLB...` continua aberta.
        # Granularidade caiu para categoria-pai; `trust_hint=False` evita que
        # o classifier confie no hint quando a categoria-pai mistura códigos
        # (ex.: vestuário fem+masc no mesmo MLB1430).
        'casa_cozinha': {
            'urls': [
                ('Casa Móveis Decoração', 'https://www.mercadolivre.com.br/ofertas?category=MLB1574'),
            ],
            'priority_brands': ('tramontina', 'mondial', 'oster', 'brastemp', 'electrolux'),
            'min_discount': 20,
            'max_price': 800.0,  # 600 → 800 (2026-08-23): teto mordia — máx. coletado caiu de R$ 5.299 para R$ 642
            'cycle_limit': 25,
            'fallback': 'generic',
        },
        'moda_feminina': {
            # Único slot para todo vestuário (MLB1430 mistura fem+masc).
            # trust_hint=False → classifier de keywords reparte fem/masc por título.
            'urls': [
                ('Calçados Roupas Bolsas', 'https://www.mercadolivre.com.br/ofertas?category=MLB1430', False),
            ],
            'priority_brands': ('havaianas', 'nike', 'adidas', 'mizuno', 'colcci'),
            'min_discount': 25,
            # 400 → 600 (2026-08-23). Sem efeito prático hoje: este alvo é
            # trust_hint=False, então não passa por _apply_category_filters.
            # Alinhado com os demais para o dia em que o hint voltar a existir.
            'max_price': 600.0,
            'cycle_limit': 40,
            'fallback': 'generic',
        },
        'moda_masculina': {
            # Coberto pelo slot único de 'moda_feminina' acima — o classifier
            # de keywords reparte fem/masc; manter aqui só pra cycle_limit/score.
            'urls': [],
            'priority_brands': ('insider', 'nike', 'adidas', 'mizuno', 'fila'),
            'min_discount': 20,
            'max_price': 600.0,  # 500 → 600 (2026-08-23): moda paga 16–26%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'infantil': {
            'urls': [
                ('Brinquedos e Hobbies', 'https://www.mercadolivre.com.br/ofertas?category=MLB1132'),
                ('Bebês', 'https://www.mercadolivre.com.br/ofertas?category=MLB1384'),
            ],
            'priority_brands': ('mattel', 'hasbro', 'lego', 'estrela', 'fisher-price'),
            'min_discount': 25,
            'max_price': 500.0,  # 400 → 500 (2026-08-23): teto mordia — máx. coletado caiu de R$ 1.549 para R$ 399
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'tecnologia_cotidiana': {
            'urls': [
                ('Celulares e Telefones', 'https://www.mercadolivre.com.br/ofertas?category=MLB1051'),
                ('Eletrônicos Áudio Vídeo', 'https://www.mercadolivre.com.br/ofertas?category=MLB1000'),
            ],
            'priority_brands': ('xiaomi', 'samsung', 'jbl', 'sony', 'motorola'),
            'min_discount': 20,
            'max_price': 500.0,  # 700 → 500 (2026-08-23): celular pagou 5% num ticket de R$ 637 — pior relação do arquivo
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'beleza_cuidados': {
            'urls': [
                ('Beleza e Cuidado Pessoal', 'https://www.mercadolivre.com.br/ofertas?category=MLB1246'),
            ],
            'priority_brands': ('avon', 'natura', 'eudora', 'o boticario', 'loreal', 'elseve', 'oral-b', 'taiff', 'kerastase', 'lattafa', 'afnan', 'armaf', 'rasasi', 'al haramain', 'maison alhambra', 'swiss arabian', 'khadlaj', 'fragrance world', 'paris corner', 'asdaaf', 'ajmal', 'al wataniah', 'ard al zaafaran'),
            'min_discount': 25,
            # 300 → 800 (2026-08-23). O teto mais danoso do arquivo: o preço máximo
            # de oferta de beleza coletada no ML caiu de R$ 819 (maio) para R$ 299,
            # e o kit de perfume que rendeu R$ 94,16 a 16% custava R$ 717.
            'max_price': 800.0,
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'saude_suplementacao': {
            # MLB1276 é Esportes inteiro (tênis, bikes, suplementos misturados).
            # trust_hint=False → keyword classifier decide quem é suplemento.
            'urls': [
                ('Esportes e Fitness', 'https://www.mercadolivre.com.br/ofertas?category=MLB1276', False),
            ],
            'priority_brands': ('growth', 'max titanium', 'dark lab', 'integralmedica', 'vitafor', 'dux nutrition', 'adaptogen', 'soldiers nutrition', 'atlhetica nutrition', 'bodyaction', 'probiótica', 'essential nutrition', 'nutrify', 'optimum nutrition', 'universal nutrition', 'muscletech', 'black skull'),
            'min_discount': 30,
            'max_price': 250.0,
            'cycle_limit': 5,
            'fallback': 'skip',
        },
    },
    'shopee': {
        'casa_cozinha': {
            'urls': [
                ('Casa e Cozinha', 100636),
                ('Eletrodomésticos', 100010),
            ],
            'priority_brands': ('tramontina', 'mondial', 'oster', 'arno', 'electrolux'),
            'min_discount': 15,
            'max_price': 800.0,  # 600 → 800 (2026-08-23): cozinha paga 16,8%
            'cycle_limit': 25,
            'fallback': 'generic',
        },
        'tecnologia_cotidiana': {
            'urls': [
                ('Celulares e Gadgets', 100013),
                ('Áudio e Eletrônicos', 100535),
                ('Computadores e Acessórios', 100644),
            ],
            'priority_brands': ('samsung', 'xiaomi', 'jbl', 'sony', 'logitech'),
            'min_discount': 15,
            'max_price': 500.0,  # 800 → 500 (2026-08-23): comissão de eletrônico é 2,5–6,8%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'beleza_cuidados': {
            'urls': [
                ('Beleza e Cuidados Pessoais', 100630),
            ],
            'priority_brands': ('avon', 'natura', 'eudora', 'o boticario', 'loreal', 'elseve', 'oral-b', 'taiff', 'lattafa', 'afnan', 'armaf', 'rasasi', 'al haramain', 'maison alhambra', 'swiss arabian', 'khadlaj', 'fragrance world', 'paris corner', 'asdaaf', 'ajmal', 'al wataniah', 'ard al zaafaran'),
            'min_discount': 20,
            'max_price': 800.0,  # 400 → 800 (2026-08-23): perfumaria paga 16% com ticket de R$ 416
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'moda_feminina': {
            'urls': [
                ('Moda Feminina', 100017),
                ('Calçados e Bolsas', 100532),
            ],
            'priority_brands': ('nike', 'adidas', 'mizuno', 'havaianas'),
            'min_discount': 20,
            'max_price': 600.0,  # 500 → 600 (2026-08-23): moda paga 16–26%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'moda_masculina': {
            # IDs descobertos via keyword search na productOfferV2 (não há query
            # de listagem de categorias na Affiliate API) — camiseta/bermuda/cueca
            # masculina retornam productCatIds=[100011, ...] de forma consistente
            # (42/60 hits); confirmado direto com productCatId=100011 trazendo só
            # roupa masculina. 100012 idem para calçados/acessórios masculinos
            # (palmilha, chinelo, tênis, sem itens femininos misturados).
            'urls': [
                ('Moda Masculina', 100011),
                ('Calçados e Acessórios Masculinos', 100012),
            ],
            'priority_brands': ('insider', 'nike', 'adidas', 'puma', 'fila', 'mizuno', 'asics', 'new balance', 'under armour', 'oakley', 'vans', 'converse', 'calvin klein', 'tommy hilfiger'),
            'min_discount': 20,
            'max_price': 600.0,  # 500 → 600 (2026-08-23): moda paga 16–26%
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'infantil': {
            'urls': [
                ('Brinquedos e Hobbies', 100639),
                ('Bebês', 100632),
                ('Moda Bebê', 100633),
            ],
            'priority_brands': ('mattel', 'hasbro', 'lego', 'fisher-price'),
            'min_discount': 15,
            'max_price': 500.0,  # 400 → 500 (2026-08-23): brinquedo paga 11–16%
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'saude_suplementacao': {
            # 100001 é "Saúde" genérico (escova elétrica, balança, nebulizador —
            # fora do escopo). 100002 é o nível "Suplementos Alimentares" dentro
            # de Saúde — testado direto e retornou só whey/creatina/vitaminas/
            # pré-treino, alinhado com priority_brands abaixo. Mesmo padrão de
            # exposição limitada usado em amazon/mercadolivre (cycle_limit=5,
            # fallback=skip — viés do dono, não é limite de oferta da API).
            'urls': [
                ('Suplementos Alimentares', 100002),
            ],
            'priority_brands': ('growth', 'max titanium', 'dark lab', 'integralmedica', 'vitafor', 'dux nutrition', 'adaptogen', 'soldiers nutrition', 'atlhetica nutrition', 'bodyaction', 'probiótica', 'essential nutrition', 'nutrify', 'optimum nutrition', 'universal nutrition', 'muscletech', 'black skull'),
            'min_discount': 25,
            'max_price': 300.0,
            'cycle_limit': 5,  # exposição limitada — viés do dono (mesmo padrão amazon/ml)
            'fallback': 'skip',
        },
    },
}


def get_targets(marketplace_code: str) -> dict[str, dict]:
    return CATEGORY_TARGETS.get(marketplace_code, {})


def flatten_urls(marketplace_code: str) -> list[CategoryTarget]:
    out: list[CategoryTarget] = []
    for category_code, cfg in get_targets(marketplace_code).items():
        for entry in cfg.get('urls', []):
            label, url, *rest = entry
            trust_hint = rest[0] if rest else True
            out.append(
                CategoryTarget(
                    marketplace=marketplace_code,
                    category_code=category_code,
                    label=label,
                    url=url,
                    trust_hint=trust_hint,
                )
            )
    return out
