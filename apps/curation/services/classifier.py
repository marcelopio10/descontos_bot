import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.curation.services.settings import get_integer_setting


if TYPE_CHECKING:
    from apps.offers.models import Category, Offer


log = logging.getLogger('apps.curation.classifier')

FEATURE_FLAG_KEY = 'categories_enabled'
FALLBACK_CATEGORY_CODE = 'outros'


KEYWORDS: dict[str, tuple[str, ...]] = {
    'casa_cozinha': (
        'panela', 'panelas', 'frigideira', 'wok', 'jogo de panela',
        'aspirador', 'aspiradora', 'robo aspirador', 'vassoura', 'rodo',
        'jogo de cama', 'lencol', 'fronha', 'edredom', 'cobertor', 'manta',
        'jogo de banho', 'toalha', 'toalhas', 'roupao',
        'pipoqueira', 'liquidificador', 'batedeira', 'mixer', 'sanduicheira',
        'cafeteira', 'air fryer', 'fritadeira', 'microondas', 'forno eletrico',
        'utensilio', 'utensilios', 'organizador', 'organizadora', 'cesto',
        'travesseiro', 'almofada', 'cortina', 'tapete', 'tapetes',
        'prato', 'pratos', 'copo', 'copos', 'talher', 'talheres', 'faqueiro',
        'panela de pressao', 'panela eletrica', 'fogao', 'cooktop',
        'casa', 'cozinha', 'mesa posta', 'jogo americano',
    ),
    'moda_feminina': (
        'vestido', 'vestidos', 'blusa feminina', 'blusas femininas',
        'sandalia feminina', 'sandalias femininas', 'sandalia', 'sandalias',
        'tenis feminino', 'bolsa feminina', 'bolsa', 'bolsas',
        'saia', 'saias', 'cropped', 'regata feminina',
        'salto', 'scarpin', 'rasteirinha', 'plus size',
        'sutia', 'lingerie', 'calcinha', 'pijama feminino',
        'short feminino', 'shorts feminino', 'calca feminina', 'calcas femininas',
    ),
    'moda_masculina': (
        'camiseta masculina', 'camisetas masculinas', 'camisa masculina',
        'insider', 'polo masculina', 'polo masculino',
        'tenis masculino', 'tenis ', 'bermuda', 'bermudas',
        'cueca', 'cuecas', 'meia masculina', 'pijama masculino',
        'calca masculina', 'calcas masculinas', 'short masculino',
        'sapato social', 'mocassim', 'jaqueta masculina', 'moletom masculino',
        'kit camiseta', 'kit camisetas',
    ),
    'infantil': (
        'brinquedo', 'brinquedos', 'boneca', 'bonecas', 'boneco',
        'lego', 'playmobil', 'pelucia', 'pelucias',
        'jogo infantil', 'jogos infantis', 'quebra-cabeca', 'quebra cabeca',
        'carrinho de bebe', 'mamadeira', 'fralda', 'fraldas',
        'roupa infantil', 'roupa de bebe', 'menino', 'menina',
        'mochila escolar', 'lancheira', 'estojo escolar',
        'patinete', 'triciclo', 'bicicleta infantil',
        'criança', 'crianca', 'kids', 'bebe',
    ),
    'beleza_cuidados': (
        'secador', 'secador de cabelo', 'chapinha', 'prancha de cabelo',
        'escova rotativa', 'escova alisadora', 'modelador',
        'skincare', 'serum', 'creme facial', 'protetor solar',
        'maquiagem', 'batom', 'base liquida', 'rimel', 'mascara de cilios',
        'shampoo', 'condicionador', 'mascara capilar', 'leave in',
        'perfume', 'perfumaria', 'colonia feminina', 'colonia masculina',
        'hidratante', 'esfoliante', 'sabonete liquido',
        'aparelho de barbear', 'depilador', 'depiladora',
    ),
    'tecnologia_cotidiana': (
        'fone bluetooth', 'fones bluetooth', 'fone de ouvido',
        'caixa de som', 'caixa bluetooth', 'speaker',
        'carregador', 'cabo usb', 'cabo lightning', 'cabo tipo c', 'cabo c',
        'power bank', 'powerbank', 'bateria portatil',
        'extensao eletrica', 'extensão', 'filtro de linha',
        'capa celular', 'capinha', 'pelicula',
        'smartwatch', 'smart watch', 'mi band', 'pulseira inteligente',
        'mouse', 'teclado', 'webcam', 'pendrive', 'cartao de memoria',
        'roteador', 'amplificador wifi', 'echo dot', 'alexa',
        'tv box', 'fire stick',
    ),
    'saude_suplementacao': (
        'creatina', 'whey', 'whey protein', 'proteina',
        'magnesio', 'nac', 'vitafor', 'vitamina', 'vitaminas',
        'omega 3', 'omega3', 'colageno', 'multivitaminico',
        'pre treino', 'pre-treino', 'bcaa', 'glutamina',
        'termogenico', 'queimador de gordura',
    ),
    'pet': (
        'racao', 'ração', 'caixa de areia', 'arranhador',
        'caminha pet', 'coleira', 'guia para cachorro', 'guia para cao',
        'brinquedo pet', 'petisco', 'osso recreativo',
        'cachorro', 'gato', 'pet shop', 'pet ',
        'aquario', 'aquário', 'tartaruga', 'passaro',
    ),
    'bebidas': (
        'vinho', 'vinhos', 'cerveja', 'cervejas', 'champagne',
        'espumante', 'whisky', 'whiskey', 'gin', 'vodka', 'cachaca',
        'destilado', 'aguardente', 'rum', 'tequila',
        'bebida alcoolica', 'bebidas alcoolicas',
    ),
    'automotivo': (
        'pneu', 'pneus', 'oleo motor', 'oleo lubrificante',
        'capa para carro', 'capa banco', 'tapete carro',
        'cera automotiva', 'limpa parabrisa',
        'cabo chupeta', 'bateria automotiva',
        'kit ferramentas automotivo', 'compressor de ar',
        'macaco hidraulico', 'triangulo de seguranca',
    ),
    'ferramentas': (
        'furadeira', 'parafusadeira', 'serra circular', 'serra tico-tico',
        'martelo', 'chave de fenda', 'chave philips', 'kit ferramentas',
        'esmerilhadeira', 'lixadeira', 'plaina',
        'multimetro', 'morsa', 'bancada',
    ),
    'construcao': (
        'cimento', 'argamassa', 'tijolo', 'bloco de concreto',
        'alvenaria', 'fachada', 'rejunte', 'massa corrida',
        'tinta latex', 'tinta acrilica', 'tubo pvc', 'cano pvc',
        'telha', 'porcelanato', 'piso ceramico', 'azulejo',
    ),
    'industrial': (
        'motor estacionario', 'motor industrial', 'gerador a diesel',
        'compressor industrial', 'inversor de frequencia',
        'tela soldada', 'arame farpado', 'luminaria publica',
        'etiqueta couche', 'etiqueta industrial', 'insumo',
        'peca de reposicao industrial', 'veiculo pesado',
        'shampoo automotivo profissional',
    ),
}


HINT_TO_CATEGORY: dict[str, str] = {
    'casa e cozinha': 'casa_cozinha',
    'moda': 'moda_feminina',
    'moda feminina': 'moda_feminina',
    'moda masculina': 'moda_masculina',
    'beleza': 'beleza_cuidados',
    'beleza e cuidados pessoais': 'beleza_cuidados',
    'brinquedos': 'infantil',
    'infantil': 'infantil',
    'eletronicos': 'tecnologia_cotidiana',
    'eletrônicos': 'tecnologia_cotidiana',
    'tecnologia': 'tecnologia_cotidiana',
    'esporte e lazer': 'outros',
    'esporte': 'outros',
    'vinhos': 'bebidas',
    'bebidas alcoolicas': 'bebidas',
    'bebidas alcoólicas': 'bebidas',
    'supermercado': 'outros',
    'mais vendidos': 'outros',
    'maiores altas': 'outros',
    'saude': 'saude_suplementacao',
    'saude e suplementacao': 'saude_suplementacao',
    'pet': 'pet',
    'automotivo': 'automotivo',
    'ferramentas': 'ferramentas',
    'construcao': 'construcao',
    'construção': 'construcao',
    'industrial': 'industrial',
}


@dataclass(frozen=True)
class ClassificationResult:
    category_code: str
    source: str
    matched_terms: tuple[str, ...]


def is_enabled() -> bool:
    return bool(get_integer_setting(FEATURE_FLAG_KEY, 1))


def classify(
    title: str,
    normalized_title: str = '',
    source_label: str = '',
    marketplace_code: str = '',
) -> ClassificationResult:
    haystack = _normalize(f'{title or ""} {normalized_title or ""}')
    if any(term in haystack for term in (
        'sapateira', 'armario de sapatos', 'armario para sapatos',
        'organizador de sapatos', 'porta sapatos',
    )):
        return ClassificationResult(
            category_code=FALLBACK_CATEGORY_CODE,
            source='editorial_exclusion',
            matched_terms=(),
        )

    matches = _match_keywords(haystack)
    if matches:
        best_code, terms = _pick_best_match(matches)
        return ClassificationResult(
            category_code=best_code,
            source='keyword:title',
            matched_terms=tuple(terms),
        )

    hint_code = _resolve_hint(source_label)
    if hint_code:
        return ClassificationResult(
            category_code=hint_code,
            source='hint:source_label',
            matched_terms=(_normalize(source_label),),
        )

    return ClassificationResult(
        category_code=FALLBACK_CATEGORY_CODE,
        source='fallback:outros',
        matched_terms=(),
    )


def apply_classification(offer: 'Offer') -> 'ClassificationResult | None':
    if not is_enabled():
        return None

    from apps.offers.models import Category

    payload = offer.raw_payload or {}
    source_label = str(payload.get('source_label') or payload.get('categoria_origem') or '')
    category_hint = str(payload.get('category_hint') or '')

    if category_hint:
        # Sprint 5: scraper segmentado já sabe a categoria de origem.
        # Confiança alta — a oferta veio de URL específica daquela categoria.
        result = ClassificationResult(
            category_code=category_hint,
            source='hint:scraper_target',
            matched_terms=(category_hint,),
        )
    else:
        result = classify(
            title=offer.title,
            normalized_title=offer.normalized_title,
            source_label=source_label,
            marketplace_code=offer.marketplace.code if offer.marketplace_id else '',
        )

    category = Category.objects.filter(code=result.category_code, is_active=True).first()
    if category is None:
        category = Category.objects.filter(code=FALLBACK_CATEGORY_CODE, is_active=True).first()
        if category is None:
            log.warning(
                'classifier_missing_fallback offer_id=%s code=%s',
                offer.id, result.category_code,
            )
            return result

    if offer.category_id != category.id or offer.category_source != result.source:
        offer.category = category
        offer.category_source = result.source
        offer.save(update_fields=['category', 'category_source', 'updated_at'])

    log.info(
        'classifier_applied offer_id=%s marketplace=%s category=%s source=%s terms=%s title=%r',
        offer.id,
        offer.marketplace.code if offer.marketplace_id else '',
        category.code,
        result.source,
        list(result.matched_terms),
        (offer.title or '')[:120],
    )
    return result


def _match_keywords(haystack: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for category_code, terms in KEYWORDS.items():
        for term in terms:
            pattern = r'\b' + re.escape(_normalize(term)) + r'\b'
            if re.search(pattern, haystack):
                found.setdefault(category_code, []).append(term)
    return found


def _pick_best_match(matches: dict[str, list[str]]) -> tuple[str, list[str]]:
    ranked = sorted(
        matches.items(),
        key=lambda item: (-len(item[1]), -_priority(item[0]), item[0]),
    )
    code, terms = ranked[0]
    return code, terms


def _priority(code: str) -> int:
    order = (
        'casa_cozinha',
        'moda_feminina',
        'moda_masculina',
        'infantil',
        'tecnologia_cotidiana',
        'beleza_cuidados',
        'saude_suplementacao',
        'pet',
        'bebidas',
        'automotivo',
        'ferramentas',
        'construcao',
        'industrial',
        'outros',
    )
    return len(order) - order.index(code) if code in order else 0


def _resolve_hint(source_label: str) -> str:
    if not source_label:
        return ''
    return HINT_TO_CATEGORY.get(_normalize(source_label), '')


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text or '')
    stripped = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', stripped.lower()).strip()
