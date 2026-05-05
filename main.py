"""
Motor de Ofertas — Mercado Livre (Fase 2)
==========================================
Busca as Ofertas do Dia do Mercado Livre via Web Scraping,
navegando por até 5 páginas (~240 ofertas) e exportando
somente as ofertas ativas no dia de hoje.
"""

import json
import os
import time
import logging
import re
import random
from datetime import datetime, timezone, timedelta
from typing import Optional
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    cffi_requests = requests  # type: ignore
    _CURL_CFFI_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BRT_OFFSET  = timedelta(hours=-3)
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "ofertas.json")

# ─── Configurações do Scraper ────────────────────────────────────────────────
MAX_PAGES      = 5        # Número de páginas de ofertas a percorrer
MIN_DISCOUNT   = 5        # Desconto mínimo (%) para incluir no resultado
DELAY_MIN      = 2.0      # Delay mínimo (s) entre páginas
DELAY_MAX      = 4.5      # Delay máximo (s) entre páginas


class MercadoLivreScraper:
    def __init__(self, affiliate_id: str = "", affiliate_tag: str = "", ml_cookie: str = "", ml_csrf: str = ""):
        self.affiliate_id = affiliate_id
        self.affiliate_tag = affiliate_tag
        self.ml_cookie = ml_cookie
        self.ml_csrf = ml_csrf
        self.today = datetime.now(timezone(BRT_OFFSET)).date()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
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
        self.session = requests.Session()

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def get_html(self, url: str) -> str:
        try:
            resp = self.session.get(url, headers=self.headers, timeout=20)
            if resp.status_code == 403:
                log.error("❌ Acesso negado (403) — IP possivelmente bloqueado pelo Cloudflare. URL: %s", url)
                return ""
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            log.error("❌ Erro ao acessar '%s': %s", url, exc)
            return ""

    # ── Scraping das Ofertas do Dia ───────────────────────────────────────────

    def scrape_daily_deals(self, max_pages: int = MAX_PAGES) -> list[dict]:
        """Percorre as páginas de ofertas do ML e retorna todos os itens encontrados."""
        all_offers: list[dict] = []
        seen_ids: set[str] = set()

        for page in range(1, max_pages + 1):
            url = f"https://www.mercadolivre.com.br/ofertas?page={page}"
            log.info("📄 Buscando página %d/%d → %s", page, max_pages, url)

            html = self.get_html(url)
            if not html:
                log.warning("⚠️  Página %d sem conteúdo — encerrando paginação.", page)
                break

            # Detecção de CAPTCHA
            if "verifique que você não é um robô" in html.lower() or "captcha" in html.lower():
                log.error("❌ CAPTCHA detectado na página %d. Execute localmente para evitar bloqueios.", page)
                break

            page_offers = self._extract_poly_cards(html, page)
            new = 0
            for o in page_offers:
                if o["id"] not in seen_ids:
                    seen_ids.add(o["id"])
                    all_offers.append(o)
                    new += 1

            log.info("✅ Página %d → %d novos itens capturados (total: %d)", page, new, len(all_offers))

            # Sem mais produtos encontrados — encerra cedo
            if not page_offers:
                log.info("🏁 Nenhum produto na página %d — encerrando.", page)
                break

            if page < max_pages:
                delay = round(random.uniform(DELAY_MIN, DELAY_MAX), 2)
                log.info("⏳ Aguardando %.1fs antes da próxima página...", delay)
                time.sleep(delay)

        return all_offers

    # ── Extração dos cards ────────────────────────────────────────────────────

    def _extract_poly_cards(self, html: str, page: int) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")

        # Tenta seletores em ordem de confiança
        items = (
            soup.select(".poly-card")
            or soup.select(".ui-search-result")
            or soup.select("[class*='deals-item']")
        )

        log.info("🔍 Página %d → %d cards encontrados no HTML", page, len(items))

        offers = []
        for card in items:
            offer = self._parse_item(card)
            if offer:
                offers.append(offer)

        return offers

    def _parse_item(self, card: BeautifulSoup) -> Optional[dict]:
        try:
            # 1. Título e Link
            title_el = (
                card.select_one(".poly-component__title")
                or card.select_one(".ui-search-item__title")
                or card.select_one("a[class*='title']")
            )
            if not title_el:
                return None

            title = title_el.get_text(strip=True)
            permalink = title_el.get("href", "")
            
            # Se for um link de anúncio (click1), extrai a URL real
            if "click1.mercadolivre" in permalink or "mclics" in permalink:
                import urllib.parse
                parsed = urllib.parse.urlparse(permalink)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'url' in qs:
                    permalink = qs['url'][0]
            
            # Limpa âncoras e trackers internos do link
            if "?" in permalink:
                permalink = permalink.split("?")[0]
            if "#" in permalink:
                permalink = permalink.split("#")[0]

            if not permalink or not title:
                return None

            # 2. ID do produto (MLBxxxxxxxx)
            item_id = "MLB000000000"
            match = re.search(r"(MLB[\-]?\d+)", permalink)
            if match:
                item_id = match.group(1).replace("-", "")
            else:
                # Fallback: gera ID do título
                item_id = f"MLB_{''.join(filter(str.isalnum, title[:20]))}"

            # 3. Preço atual
            price_fraction = (
                card.select_one(".poly-price__current .andes-money-amount__fraction")
                or card.select_one(".andes-money-amount__fraction")
            )
            price = 0.0
            if price_fraction:
                try:
                    price = float(price_fraction.get_text(strip=True).replace(".", "").replace(",", "."))
                except ValueError:
                    pass
            if price <= 0:
                return None

            # 4. Preço original
            orig_price = price
            s_price_el = (
                card.select_one("s.andes-money-amount--previous .andes-money-amount__fraction")
                or card.select_one(".poly-price__original .andes-money-amount__fraction")
                or card.select_one("[class*='original'] .andes-money-amount__fraction")
            )
            if s_price_el:
                try:
                    orig_price = float(s_price_el.get_text(strip=True).replace(".", "").replace(",", "."))
                except ValueError:
                    pass

            # 5. Percentual de desconto
            desconto_pct = 0
            discount_el = card.select_one(".poly-price__discount") or card.select_one("[class*='discount']")
            if discount_el:
                m = re.search(r"(\d+)\s*%", discount_el.get_text())
                if m:
                    desconto_pct = int(m.group(1))

            # Calcula se não encontrou no badge
            if desconto_pct == 0 and orig_price > price:
                desconto_pct = round((orig_price - price) / orig_price * 100)

            # Filtra itens sem desconto relevante
            if desconto_pct < MIN_DISCOUNT:
                return None

            # 6. Imagem
            img_el = (
                card.select_one(".poly-component__picture")
                or card.select_one("img[class*='item']")
                or card.select_one("img")
            )
            img = ""
            if img_el:
                img = img_el.get("data-src") or img_el.get("src", "")
            img = (
                img
                .replace("http://", "https://")
                .replace("-W.webp", "-O.webp")
                .replace("-E.webp", "-O.webp")
                .replace("-V.webp", "-O.webp")
            )

            # 7. Frete grátis
            shipping_el = card.select_one(".poly-component__shipping") or card.select_one("[class*='shipping']")
            has_free_shipping = bool(
                shipping_el and any(kw in shipping_el.get_text().lower() for kw in ["grátis", "gratis", "free"])
            )

            # 8. Vendedor
            seller_el = card.select_one(".poly-component__seller") or card.select_one("[class*='seller']")
            seller = "Top Vendedor ML"
            if seller_el:
                seller = seller_el.get_text(strip=True).replace("Por", "").strip() or seller

            # 9. Link de afiliado oficial via API interna
            link_afi = self._gerar_link_afiliado_oficial(permalink)

            return {
                "id":             item_id,
                "nome":           title,
                "preco":          price,
                "preco_original": orig_price,
                "desconto_pct":   desconto_pct,
                "link_direto":    permalink,
                "link_afiliado":  link_afi,
                "imagem":         img,
                "vendedor":       seller,
                "condicao":       "Novo",
                "frete_gratis":   has_free_shipping,
                "data":           datetime.now(timezone(BRT_OFFSET)).strftime("%Y-%m-%d"),
            }

        except Exception as exc:
            log.debug("⚠️  Erro ao parsear card: %s", exc)
            return None

    def _exibir_alerta_cookie(self) -> None:
        if getattr(self, '_alerta_exibido', False):
            return
        self._alerta_exibido = True
        
        msg = """
================================================================================
🚨 ATENÇÃO: O COOKIE DO MERCADO LIVRE EXPIROU OU ESTÁ AUSENTE! 🚨
================================================================================

Os seus links não estão sendo rastreados pelo programa de afiliados.
Os posts enviados agora gerarão vendas SEM COMISSÃO para você.

COMO RENOVAR A SESSÃO (Demora 30 segundos):
1. Abra o navegador onde você está logado no Mercado Livre.
2. Pressione F12 para abrir o "Inspecionar" e vá na aba "Network" (Rede).
3. Acesse seu painel: https://www.mercadolivre.com.br/affiliate-program
4. Na aba Network, encontre alguma requisição para a API do ML.
5. Clique nela com o botão direito -> "Copy" -> "Copy as cURL (bash)".
6. Extraia a string do 'cookie:' e cole no arquivo .env (ML_COOKIE=...).
7. Extraia o 'x-csrf-token:' e cole no .env (ML_CSRF_TOKEN=...).
8. Salve o arquivo .env e reinicie o orquestrador!
================================================================================
"""
        log.error(msg)

    def _gerar_link_afiliado_oficial(self, permalink: str) -> str:
        if not permalink:
            return permalink
            
        if not self.ml_cookie or not self.ml_csrf or not self.affiliate_tag:
            self._exibir_alerta_cookie()
            return permalink
            
        url_api = 'https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links'
        headers = {
            'accept': 'application/json, text/plain, */*',
            'content-type': 'application/json',
            'cookie': self.ml_cookie,
            'origin': 'https://www.mercadolivre.com.br',
            'referer': permalink,
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
            'x-csrf-token': self.ml_csrf
        }
        data = {
            "url": permalink,
            "tag": self.affiliate_tag
        }
        
        try:
            resp = self.session.post(url_api, headers=headers, json=data, timeout=10)
            if resp.ok:
                resp_data = resp.json()
                return resp_data.get("short_url", permalink)
            elif resp.status_code in (401, 403):
                self._exibir_alerta_cookie()
            else:
                log.error(f"Erro na API de Afiliados (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            log.error(f"Erro ao gerar link de afiliado oficial: {e}")
            
        return permalink


# ─── Exportador JSON ──────────────────────────────────────────────────────────

class JSONExporter:
    def __init__(self, filepath: str = OUTPUT_FILE):
        self.filepath = filepath

    def export(self, ofertas: list[dict]) -> None:
        payload = {
            "updated_at": datetime.now(timezone(BRT_OFFSET)).isoformat(),
            "total":      len(ofertas),
            "ofertas":    ofertas,
        }
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("💾 %s atualizado com %d ofertas.", self.filepath, len(ofertas))


# ─── Motor de Ofertas ─────────────────────────────────────────────────────────

class MotorDeOfertas:
    def __init__(self):
        self.scraper  = MercadoLivreScraper(
            affiliate_id=os.environ.get("ML_AFFILIATE_ID", ""),
            affiliate_tag=os.environ.get("ML_AFFILIATE_TAG", ""),
            ml_cookie=os.environ.get("ML_COOKIE", ""),
            ml_csrf=os.environ.get("ML_CSRF_TOKEN", "")
        )
        self.exporter = JSONExporter()

    def run(self) -> None:
        log.info("🤖 Motor de Ofertas Iniciado — %s", datetime.now(timezone(BRT_OFFSET)).strftime("%d/%m/%Y %H:%M BRT"))
        log.info("📋 Configuração: %d páginas de ofertas do dia", MAX_PAGES)

        # Coleta todas as ofertas do dia
        ofertas = self.scraper.scrape_daily_deals(max_pages=MAX_PAGES)

        if not ofertas:
            log.warning("⚠️  Nenhuma oferta encontrada. Verifique conexão ou bloqueios.")
        else:
            # Ordena por maior desconto
            ofertas.sort(key=lambda o: o["desconto_pct"], reverse=True)
            log.info("🏆 Top 3 ofertas por desconto:")
            for i, o in enumerate(ofertas[:3], 1):
                log.info("  %d. %s — %d%% OFF — R$ %.2f", i, o["nome"][:50], o["desconto_pct"], o["preco"])

        self.exporter.export(ofertas)
        log.info("🏁 Concluído. Total de ofertas únicas: %d", len(ofertas))


if __name__ == "__main__":
    motor = MotorDeOfertas()
    motor.run()
