"""Configuração declarativa de scraping orientado a categorias (Sprint 5).

Cada entrada cobre uma das categorias prioritárias para o público real
(DF, 35+, familiar). O scraper genérico (scrape_daily_deals) continua
disponível como fallback — Sprint 5 acrescenta caminho complementar
sem remover o atual.

Estrutura:
    {
        marketplace_code: {
            category_code: {
                'urls':           [(rotulo, url), ...],
                'priority_brands': (str, ...),     # informativo (consumido pelo score)
                'min_discount':    int,            # filtro pós-extração
                'max_price':       float | None,
                'cycle_limit':     int,            # corte por categoria/ciclo
                'fallback':        'generic' | 'skip',
            }
        }
    }
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryTarget:
    marketplace: str
    category_code: str
    label: str
    url: str
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
            'max_price': 600.0,
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
            'max_price': 500.0,
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'moda_masculina': {
            'urls': [
                ('Moda Masculina', 'https://www.amazon.com.br/s?k=camiseta+masculina&i=apparel&deal-type=eligible'),
                ('Calçados Masculinos', 'https://www.amazon.com.br/s?k=tenis+masculino&i=shoes&deal-type=eligible'),
            ],
            'priority_brands': ('insider', 'nike', 'adidas', 'puma', 'fila', 'mizuno'),
            'min_discount': 15,
            'max_price': 500.0,
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
            'max_price': 400.0,
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
            'max_price': 800.0,
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'beleza_cuidados': {
            'urls': [
                ('Beleza', 'https://www.amazon.com.br/s?k=beleza&i=beauty&deal-type=eligible'),
                ('Cuidados Pessoais', 'https://www.amazon.com.br/s?k=skincare&i=beauty&deal-type=eligible'),
            ],
            'priority_brands': ('avon', 'natura', 'eudora', 'oral-b', 'colgate', 'taiff'),
            'min_discount': 20,
            'max_price': 400.0,
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'saude_suplementacao': {
            'urls': [
                ('Saúde — Suplementos', 'https://www.amazon.com.br/s?k=suplemento&i=hpc&deal-type=eligible'),
            ],
            'priority_brands': ('growth', 'integralmedica', 'max titanium', 'vitafor'),
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
            'max_price': 600.0,
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
            'max_price': 400.0,
            'cycle_limit': 40,
            'fallback': 'generic',
        },
        'moda_masculina': {
            # Coberto pelo slot único de 'moda_feminina' acima — o classifier
            # de keywords reparte fem/masc; manter aqui só pra cycle_limit/score.
            'urls': [],
            'priority_brands': ('insider', 'nike', 'adidas', 'mizuno', 'fila'),
            'min_discount': 20,
            'max_price': 500.0,
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
            'max_price': 400.0,
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
            'max_price': 700.0,
            'cycle_limit': 20,
            'fallback': 'generic',
        },
        'beleza_cuidados': {
            'urls': [
                ('Beleza e Cuidado Pessoal', 'https://www.mercadolivre.com.br/ofertas?category=MLB1246'),
            ],
            'priority_brands': ('avon', 'natura', 'eudora', 'oral-b', 'taiff'),
            'min_discount': 25,
            'max_price': 300.0,
            'cycle_limit': 15,
            'fallback': 'generic',
        },
        'saude_suplementacao': {
            # MLB1276 é Esportes inteiro (tênis, bikes, suplementos misturados).
            # trust_hint=False → keyword classifier decide quem é suplemento.
            'urls': [
                ('Esportes e Fitness', 'https://www.mercadolivre.com.br/ofertas?category=MLB1276', False),
            ],
            'priority_brands': ('growth', 'integralmedica', 'max titanium', 'vitafor'),
            'min_discount': 30,
            'max_price': 250.0,
            'cycle_limit': 5,
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
