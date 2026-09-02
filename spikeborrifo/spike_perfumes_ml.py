"""
Spike de volume — ofertas de perfume no Mercado Livre.

Objetivo: medir quantas ofertas sobrevivem a cada estagio do funil antes de
escrever o PRD. NAO envia nada, NAO cunha link de afiliado, NAO precisa de
cookie do ML. So le paginas publicas de oferta por categoria e conta.

Autocontido de proposito: nenhum import do descontos.bot.

Uso:
    pip install beautifulsoup4 curl_cffi requests

    # 1. descobrir os IDs de categoria de perfumaria
    python spike_perfumes_ml.py --discover

    # 2. rodar o funil (edite CATEGORY_TARGETS com os IDs achados no passo 1)
    python spike_perfumes_ml.py

    # variacoes uteis
    python spike_perfumes_ml.py --pages 3        # testa se paginacao funciona
    python spike_perfumes_ml.py --min-rating 4.5 --min-reviews 30
    python spike_perfumes_ml.py --dump saida.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as curl_requests
    HAS_CURL_CFFI = False


# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------

# Preencha depois de rodar --discover. Formato: (codigo, rotulo)
CATEGORY_TARGETS: list[tuple[str, str]] = [
    ("MLB1246", "Beleza e Cuidado Pessoal (raiz — trocar pelos filhos)"),
]

OFFERS_URL = "https://www.mercadolivre.com.br/ofertas?category={code}&page={page}"
API_CATEGORIES = "https://api.mercadolibre.com/sites/MLB/categories"
API_CATEGORY = "https://api.mercadolibre.com/categories/{code}"

DELAY_MIN, DELAY_MAX = 2.0, 4.5
DEFAULT_MIN_DISCOUNT = 5
DEFAULT_MIN_RATING = 4.8
DEFAULT_MIN_REVIEWS = 50

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

CAPTCHA_MARKERS = (
    "captcha",
    "gz/account-verification",
    "Para continuar, confirme que",
    "challenge-platform",
)

CONCENTRATIONS = [
    (r"\beau\s*de\s*parfum\b|\bedp\b|\bparfum\b(?!\s*de)", "EDP"),
    (r"\beau\s*de\s*toilette\b|\bedt\b", "EDT"),
    (r"\beau\s*de\s*cologne\b|\bedc\b|\bcolonia\b", "EDC"),
    (r"\bbody\s*splash\b|\bdeo\s*colonia\b", "SPLASH"),
    (r"\bextrait\b|\bparfum\s*extrait\b", "EXTRAIT"),
]

USED_MARKERS = (
    r"\btester\b", r"\bdecant\b", r"\bfracionad", r"\bamostra\b",
    r"\busado\b", r"\bsem\s*caixa\b", r"\breplica\b",
)


def make_session():
    if HAS_CURL_CFFI:
        return curl_requests.Session(impersonate="chrome124")
    print("[aviso] curl_cffi ausente — chance alta de bloqueio. pip install curl_cffi")
    return curl_requests.Session()


def fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", folded).strip().lower()


# --------------------------------------------------------------------------
# Parsers (com as correcoes que faltam no scraper atual)
# --------------------------------------------------------------------------

def parse_rating(text: str) -> Optional[float]:
    """4,8 / 4.8 / 5 -> float. Ausente -> None (diferente de 0.0 real)."""
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 0.0 <= value <= 5.0 else None


def parse_review_count(text: str) -> Optional[int]:
    """(2.345) -> 2345 | 1,2 mil -> 1200 | ausente -> None."""
    if not text:
        return None
    raw = fold(text).strip("() ")
    mil = re.search(r"(\d+(?:[.,]\d+)?)\s*mil\b", raw)
    if mil:
        try:
            return int(float(mil.group(1).replace(",", ".")) * 1000)
        except ValueError:
            return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_volume_ml(title: str) -> Optional[int]:
    t = fold(title)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*ml\b", t)
    if m:
        try:
            return int(float(m.group(1).replace(",", ".")))
        except ValueError:
            return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*l\b", t)
    if m:
        try:
            return int(float(m.group(1).replace(",", ".")) * 1000)
        except ValueError:
            return None
    return None


def parse_concentration(title: str) -> Optional[str]:
    t = fold(title)
    for pattern, label in CONCENTRATIONS:
        if re.search(pattern, t):
            return label
    return None


def looks_used_or_split(title: str) -> Optional[str]:
    t = fold(title)
    for pattern in USED_MARKERS:
        if re.search(pattern, t):
            return pattern.strip("\\b")
    return None


def canonical_key(title: str, volume: Optional[int], conc: Optional[str]) -> str:
    """Chave grosseira de produto, so para medir duplicidade entre vendedores."""
    t = fold(title)
    t = re.sub(r"\d+(?:[.,]\d+)?\s*(ml|l)\b", " ", t)
    t = re.sub(r"\b(perfume|masculino|feminino|importado|original|lacrado|novo|"
               r"eau|de|parfum|toilette|cologne|edp|edt|edc|para|com|kit)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    tokens = [w for w in t.split() if len(w) > 2][:4]
    return f"{'-'.join(tokens)}|{volume or '?'}|{conc or '?'}"


# --------------------------------------------------------------------------
# Coleta
# --------------------------------------------------------------------------

@dataclass
class Card:
    item_id: str
    titulo: str
    preco: float
    preco_original: float
    desconto_pct: int
    rating: Optional[float]
    review_count: Optional[int]
    vendedor: Optional[str]
    volume_ml: Optional[int]
    concentracao: Optional[str]
    suspeita_uso: Optional[str]
    link: str
    imagem: str
    categoria: str
    chave_canonica: str = ""
    rating_raw: str = ""
    review_raw: str = ""


def is_blocked(html: str) -> bool:
    low = html.lower()
    return any(m.lower() in low for m in CAPTCHA_MARKERS) or len(html) < 20000


def parse_card(card, categoria: str) -> Optional[Card]:
    title_el = (card.select_one(".poly-component__title")
                or card.select_one(".ui-search-item__title")
                or card.select_one("a[class*=title]"))
    if not title_el:
        return None

    titulo = re.sub(r"^\s*an[uú]ncio\s+patrocinado\s*[-–—:]\s*", "",
                    title_el.get_text(strip=True), flags=re.I).strip()
    link = title_el.get("href", "") or ""
    if "click1.mercadolivre" in link or "mclics" in link:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        link = qs.get("url", [link])[0]
    link = link.split("?")[0].split("#")[0]
    if not link or not titulo:
        return None

    m = re.search(r"(MLB-?\d+)", link)
    item_id = m.group(1).replace("-", "") if m else f"MLB_{fold(titulo)[:24]}"

    frac = (card.select_one(".poly-price__current .andes-money-amount__fraction")
            or card.select_one(".andes-money-amount__fraction"))
    if not frac:
        return None
    try:
        preco = float(frac.get_text(strip=True).replace(".", "").replace(",", "."))
    except ValueError:
        return None
    if preco <= 0:
        return None

    preco_original = preco
    old = (card.select_one("s.andes-money-amount--previous .andes-money-amount__fraction")
           or card.select_one(".poly-price__original .andes-money-amount__fraction")
           or card.select_one("[class*=original] .andes-money-amount__fraction"))
    if old:
        try:
            preco_original = float(old.get_text(strip=True).replace(".", "").replace(",", "."))
        except ValueError:
            pass

    desconto = 0
    disc_el = card.select_one(".poly-price__discount") or card.select_one("[class*=discount]")
    if disc_el:
        dm = re.search(r"(\d+)\s*%", disc_el.get_text())
        if dm:
            desconto = int(dm.group(1))
    if desconto == 0 and preco_original > preco:
        desconto = round((preco_original - preco) / preco_original * 100)

    rating_el = (card.select_one(".poly-reviews__rating")
                 or card.select_one(".ui-search-reviews__rating-number"))
    count_el = (card.select_one(".poly-reviews__total")
                or card.select_one(".ui-search-reviews__amount"))
    rating_raw = rating_el.get_text(strip=True) if rating_el else ""
    review_raw = count_el.get_text(strip=True) if count_el else ""

    seller_el = card.select_one(".poly-component__seller") or card.select_one("[class*=seller]")
    vendedor = None
    if seller_el:
        vendedor = seller_el.get_text(strip=True).replace("Por", "").strip() or None

    img_el = (card.select_one(".poly-component__picture")
              or card.select_one("img[class*=item]") or card.select_one("img"))
    imagem = ""
    if img_el:
        imagem = img_el.get("data-src") or img_el.get("src", "") or ""
    for suffix in ("-W.webp", "-E.webp", "-V.webp"):
        imagem = imagem.replace(suffix, "-O.webp")
    imagem = imagem.replace("http://", "https://")

    volume = parse_volume_ml(titulo)
    conc = parse_concentration(titulo)

    return Card(
        item_id=item_id, titulo=titulo, preco=preco, preco_original=preco_original,
        desconto_pct=desconto, rating=parse_rating(rating_raw),
        review_count=parse_review_count(review_raw), vendedor=vendedor,
        volume_ml=volume, concentracao=conc, suspeita_uso=looks_used_or_split(titulo),
        link=link, imagem=imagem, categoria=categoria,
        chave_canonica=canonical_key(titulo, volume, conc),
        rating_raw=rating_raw, review_raw=review_raw,
    )


def fetch(session, url: str) -> tuple[str, str]:
    try:
        resp = session.get(url, headers=HEADERS, timeout=25)
    except Exception as exc:
        return "", f"erro: {exc}"
    if resp.status_code == 403:
        return "", "403 forbidden"
    if resp.status_code != 200:
        return "", f"http {resp.status_code}"
    html = resp.text
    if is_blocked(html):
        return "", f"bloqueado/captcha (html {len(html)}b)"
    return html, ""


# --------------------------------------------------------------------------
# Descoberta de categorias
# --------------------------------------------------------------------------

def discover(session) -> None:
    print("Buscando arvore de categorias MLB...\n")
    try:
        roots = session.get(API_CATEGORIES, timeout=20).json()
    except Exception as exc:
        print(f"Falhou: {exc}")
        return

    beleza = next((c for c in roots if "beleza" in fold(c.get("name", ""))), None)
    if not beleza:
        print("Categoria de beleza nao encontrada. Raizes disponiveis:")
        for c in roots:
            print(f"  {c['id']:<12} {c['name']}")
        return

    print(f"{beleza['id']:<12} {beleza['name']}\n")
    try:
        detail = session.get(API_CATEGORY.format(code=beleza["id"]), timeout=20).json()
    except Exception as exc:
        print(f"Falhou ao abrir filhos: {exc}")
        return

    for child in detail.get("children_categories", []):
        marker = " <<<" if "perfume" in fold(child["name"]) else ""
        print(f"  {child['id']:<12} {child['name']}{marker}")
        if "perfume" in fold(child["name"]):
            try:
                sub = session.get(API_CATEGORY.format(code=child["id"]), timeout=20).json()
                for gc in sub.get("children_categories", []):
                    print(f"      {gc['id']:<12} {gc['name']}")
            except Exception:
                pass

    print("\nCopie os IDs marcados para CATEGORY_TARGETS no topo do arquivo.")


# --------------------------------------------------------------------------
# Funil
# --------------------------------------------------------------------------

def run(args) -> None:
    session = make_session()
    if args.discover:
        discover(session)
        return

    cards: list[Card] = []
    fetch_log: list[dict] = []

    for code, label in CATEGORY_TARGETS:
        for page in range(1, args.pages + 1):
            url = OFFERS_URL.format(code=code, page=page)
            print(f"[fetch] {label} p{page} -> {url}")
            html, err = fetch(session, url)
            if err:
                print(f"         FALHOU: {err}")
                fetch_log.append({"url": url, "erro": err, "cards": 0})
                break
            soup = BeautifulSoup(html, "html.parser")
            found = (soup.select(".poly-card") or soup.select(".ui-search-result")
                     or soup.select("[class*=deals-item]"))
            parsed = [c for c in (parse_card(el, label) for el in found) if c]
            print(f"         {len(found)} cards no html, {len(parsed)} parseados")
            fetch_log.append({"url": url, "erro": "", "cards": len(found),
                              "parseados": len(parsed)})
            cards.extend(parsed)
            if not found:
                break
            time.sleep(round(random.uniform(DELAY_MIN, DELAY_MAX), 2))

    if not cards:
        print("\nNenhum card coletado. Sem dados para o funil.")
        _print_fetch_log(fetch_log)
        return

    # --- estagios do funil -------------------------------------------------
    stages: list[tuple[str, int]] = []
    stages.append(("cards parseados", len(cards)))

    by_id = {c.item_id: c for c in cards}
    stages.append(("apos dedup por item_id", len(by_id)))
    pool = list(by_id.values())

    com_desconto = [c for c in pool if c.desconto_pct >= args.min_discount]
    stages.append((f"desconto >= {args.min_discount}%", len(com_desconto)))

    com_bloco = [c for c in com_desconto if c.rating is not None or c.review_count is not None]
    stages.append(("com bloco de reviews", len(com_bloco)))

    com_ambos = [c for c in com_bloco if c.rating is not None and c.review_count is not None]
    stages.append(("com nota E contagem", len(com_ambos)))

    nota_ok = [c for c in com_ambos if c.rating >= args.min_rating]
    stages.append((f"nota >= {args.min_rating}", len(nota_ok)))

    aprovados = [c for c in nota_ok if c.review_count >= args.min_reviews]
    stages.append((f"avaliacoes >= {args.min_reviews}", len(aprovados)))

    limpos = [c for c in aprovados if not c.suspeita_uso]
    stages.append(("sem marcador de tester/decant", len(limpos)))

    canon: dict[str, list[Card]] = defaultdict(list)
    for c in limpos:
        canon[c.chave_canonica].append(c)
    stages.append(("apos dedup canonico", len(canon)))

    # --- relatorio ---------------------------------------------------------
    print("\n" + "=" * 68)
    print("FUNIL")
    print("=" * 68)
    base = stages[0][1] or 1
    for nome, n in stages:
        bar = "#" * max(1, round(n / base * 34)) if n else ""
        print(f"{nome:<32} {n:>5}  {n / base * 100:>5.1f}%  {bar}")

    print("\n" + "=" * 68)
    print("DIAGNOSTICO DE PARSING")
    print("=" * 68)
    sem_rating = [c for c in pool if c.rating is None]
    sem_count = [c for c in pool if c.review_count is None]
    mil = [c for c in pool if "mil" in fold(c.review_raw)]
    print(f"sem nota extraida ......... {len(sem_rating):>4} / {len(pool)}")
    print(f"sem contagem extraida ..... {len(sem_count):>4} / {len(pool)}")
    print(f"contagem em 'mil' ......... {len(mil):>4}   (o parser antigo erraria estes)")
    print(f"sem volume no titulo ...... {len([c for c in pool if not c.volume_ml]):>4}")
    print(f"sem concentracao .......... {len([c for c in pool if not c.concentracao]):>4}")
    print(f"sem vendedor identificado . {len([c for c in pool if not c.vendedor]):>4}")
    print(f"marcador de tester/decant . {len([c for c in pool if c.suspeita_uso]):>4}")

    if mil:
        print("\n  exemplos de contagem em milhares:")
        for c in mil[:5]:
            print(f"    '{c.review_raw}' -> {c.review_count}  | {c.titulo[:50]}")

    if sem_rating[:5]:
        print("\n  exemplos sem nota (conferir se e ausencia real ou seletor quebrado):")
        for c in sem_rating[:5]:
            print(f"    raw='{c.rating_raw}' | {c.titulo[:58]}")

    dist = Counter(round(c.rating, 1) for c in pool if c.rating is not None)
    if dist:
        print("\n  distribuicao de notas:")
        for nota in sorted(dist, reverse=True):
            print(f"    {nota:>3}  {'*' * dist[nota]} ({dist[nota]})")

    dupes = {k: v for k, v in canon.items() if len(v) > 1}
    if dupes:
        print(f"\n  {len(dupes)} chaves canonicas com mais de um anuncio:")
        for k, group in list(dupes.items())[:5]:
            print(f"    {k}")
            for c in group[:3]:
                print(f"       R$ {c.preco:>9.2f}  {c.titulo[:52]}")

    print("\n" + "=" * 68)
    print(f"APROVADOS FINAIS ({len(canon)} produtos unicos)")
    print("=" * 68)
    for k, group in canon.items():
        best = min(group, key=lambda c: c.preco)
        print(f"  R$ {best.preco:>9.2f}  -{best.desconto_pct:>2}%  "
              f"{best.rating} ({best.review_count})  "
              f"{best.volume_ml or '?'}ml {best.concentracao or '?'}")
        print(f"      {best.titulo[:70]}")

    _print_fetch_log(fetch_log)

    if args.dump:
        payload = {
            "funil": [{"estagio": n, "n": v} for n, v in stages],
            "fetch_log": fetch_log,
            "cards": [asdict(c) for c in pool],
            "aprovados": [asdict(min(g, key=lambda c: c.preco)) for g in canon.values()],
        }
        with open(args.dump, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON completo salvo em {args.dump}")


def _print_fetch_log(fetch_log: list[dict]) -> None:
    print("\n" + "=" * 68)
    print("PAGINAS")
    print("=" * 68)
    for entry in fetch_log:
        status = entry["erro"] or f"{entry['cards']} cards / {entry.get('parseados', 0)} parseados"
        print(f"  {status:<44} {entry['url'][-60:]}")


def main() -> int:
    p = argparse.ArgumentParser(description="Spike de funil — perfumes no ML")
    p.add_argument("--discover", action="store_true",
                   help="lista os IDs de categoria de perfumaria e sai")
    p.add_argument("--pages", type=int, default=1,
                   help="paginas por categoria (use 3 para testar se paginacao funciona)")
    p.add_argument("--min-discount", type=int, default=DEFAULT_MIN_DISCOUNT)
    p.add_argument("--min-rating", type=float, default=DEFAULT_MIN_RATING)
    p.add_argument("--min-reviews", type=int, default=DEFAULT_MIN_REVIEWS)
    p.add_argument("--dump", metavar="ARQUIVO.json", help="salva o resultado bruto")
    args = p.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
