# -*- coding: utf-8 -*-
"""
Gerador de Posts — descontos.bot (Fase 2)
==========================================
Ferramenta LOCAL que lê o ofertas.json e gera:
  - Textos formatados para WhatsApp (.txt)
  - Imagens 1080x1920 para Instagram Stories (.png) com QR Code do link afiliado
  - Um preview.html para visualizar todos os posts no navegador

Uso:
    python post_generator.py

Saída em output/posts/
"""

from __future__ import annotations

import io
import json
import os
import sys
import textwrap
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Garante suporte a emojis no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import qrcode
import qrcode.image.base
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ─── Caminhos ─────────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent
ASSETS_DIR     = BASE_DIR / "assets"
FONTS_DIR      = ASSETS_DIR / "fonts"
OUTPUT_DIR     = BASE_DIR / "output" / "posts"
WA_DIR         = OUTPUT_DIR / "whatsapp"
STORIES_DIR    = OUTPUT_DIR / "stories"
OFERTAS_FILE   = BASE_DIR / "ofertas.json"
AVATAR_FILE    = ASSETS_DIR / "avatar.png"

BRT_OFFSET = timedelta(hours=-3)

# ─── Paleta de cores (identidade visual descontos.bot) ────────────────────────

C_DARK       = (13,  15,  20)      # #0D0F14 — fundo principal
C_DARK2      = (22,  26,  34)      # #161A22 — fundo secundário
C_DARK3      = (30,  35,  48)      # #1E2330 — cards
C_CYAN       = (0,  201, 177)      # #00C9B1 — cor primária
C_CYAN_DIM   = (0,  158, 141)      # #009E8D — cyan mais escuro
C_YELLOW     = (255, 225,  77)     # #FFE14D — preços / badges
C_WHITE      = (244, 247, 255)     # #F4F7FF — texto principal
C_MUTED      = (138, 147, 168)     # #8A93A8 — texto secundário
C_RED_BADGE  = (220,  50,  50)     # vermelho para badge de desconto alto


# ─── Gerenciador de Fontes ────────────────────────────────────────────────────

FONT_URLS = {
    "SpaceMono-Bold":       "https://raw.githubusercontent.com/googlefonts/spacemono/main/fonts/ttf/SpaceMono-Bold.ttf",
    "SpaceMono-Regular":    "https://raw.githubusercontent.com/googlefonts/spacemono/main/fonts/ttf/SpaceMono-Regular.ttf",
    "SpaceGrotesk-Bold":    "https://raw.githubusercontent.com/floriankarsten/space-grotesk/master/fonts/ttf/static/SpaceGrotesk-Bold.ttf",
    "SpaceGrotesk-Regular": "https://raw.githubusercontent.com/floriankarsten/space-grotesk/master/fonts/ttf/static/SpaceGrotesk-Regular.ttf",
}


def ensure_fonts() -> dict[str, Path]:
    """Baixa as fontes necessarias se nao estiverem em assets/fonts/."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, url in FONT_URLS.items():
        dest = FONTS_DIR / f"{name}.ttf"
        if not dest.exists():
            print(f"  Baixando fonte {name}...")
            try:
                resp = requests.get(url, timeout=30, allow_redirects=True)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                print(f"  OK: {name} ({len(resp.content)//1024}KB)")
            except Exception as e:
                print(f"  AVISO: Nao foi possivel baixar {name}: {e}")
                print(f"  -> Usando fonte padrao como fallback.")
        paths[name] = dest
    return paths


def load_fonts(font_paths: dict[str, Path]) -> dict[str, dict[int, ImageFont.FreeTypeFont]]:
    """Carrega as fontes em varios tamanhos. Usa fonte padrao como fallback."""
    def _load(key: str, sizes: list[int]) -> dict[int, ImageFont.FreeTypeFont]:
        result = {}
        path = font_paths.get(key)
        for s in sizes:
            try:
                result[s] = ImageFont.truetype(str(path), s)
            except Exception:
                result[s] = ImageFont.load_default()
        return result

    return {
        "mono_bold":    _load("SpaceMono-Bold",       [28, 36, 48, 60, 80, 100]),
        "mono_reg":     _load("SpaceMono-Regular",     [22, 28, 36]),
        "grotesk_bold": _load("SpaceGrotesk-Bold",     [28, 36, 48, 54, 64, 80]),
        "grotesk_reg":  _load("SpaceGrotesk-Regular",  [22, 28, 36, 44]),
    }



# ─── Gerador de Texto para WhatsApp ──────────────────────────────────────────

class WhatsAppPostGenerator:
    """Gera texto formatado pronto para copiar/colar no WhatsApp."""

    def generate(self, oferta: dict) -> str:
        nome      = oferta.get("nome", "Produto")
        preco     = oferta.get("preco", 0)
        preco_ori = oferta.get("preco_original", preco)
        desc_pct  = oferta.get("desconto_pct", 0)
        frete     = oferta.get("frete_gratis", False)
        link      = oferta.get("link_afiliado") or oferta.get("link_direto", "")

        # Encurta o nome para 80 chars
        nome_curto = textwrap.shorten(nome, width=80, placeholder="...")

        frete_linha = "\n🚚 *Frete Grátis* ✈️" if frete else ""

        # Badge de intensidade
        if desc_pct >= 50:
            badge = "🚨 *OFERTA IMPERDÍVEL* 🚨"
        elif desc_pct >= 30:
            badge = "🔥 *ALERTA DO BOT* 🔥"
        else:
            badge = "⚡ *BOT ACHOU DESCONTO* ⚡"

        texto = (
            f"📦 *{nome_curto}*\n\n"
            f"{badge}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 ~De R$ {preco_ori:,.2f}~\n"
            f"✅ *Por apenas R$ {preco:,.2f}*\n"
            f"🏷️ *{desc_pct}% OFF*"
            f"{frete_linha}\n\n"
            f"🛒 Compre aqui 👇\n"
            f"{link}\n\n"
            f"⏰ Oferta por tempo limitado!\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 @descontos.bot"
        ).replace(",", ".")  # padrão BR

        return texto

    def save(self, oferta: dict, dest_dir: Path) -> Path:
        texto = self.generate(oferta)
        safe_id = oferta.get("id", "oferta").replace("/", "_")
        filepath = dest_dir / f"{safe_id}.txt"
        filepath.write_text(texto, encoding="utf-8")
        return filepath


# ─── Gerador de Instagram Stories ────────────────────────────────────────────

STORY_W = 1080
STORY_H = 1920
SAFE_TOP = 280        # área segura (evita sobreposição UI do IG)
SAFE_BOT = 300
CONTENT_TOP    = SAFE_TOP
CONTENT_BOTTOM = STORY_H - SAFE_BOT
CONTENT_W      = STORY_W - 80   # margens laterais de 40px cada lado
MARGIN         = 40


class InstagramStoryGenerator:
    """Gera imagens 1080×1920 com identidade visual do descontos.bot."""

    def __init__(self, fonts: dict, avatar_path: Optional[Path] = None):
        self.fonts = fonts
        self.avatar = None
        if avatar_path and avatar_path.exists():
            try:
                av = Image.open(avatar_path).convert("RGBA")
                av = av.resize((80, 80), Image.LANCZOS)
                self.avatar = av
            except Exception:
                pass

    # ── Helpers de desenho ───────────────────────────────────────────────────

    def _draw_rounded_rect(
        self,
        draw: ImageDraw.ImageDraw,
        xy: tuple,
        radius: int,
        fill: tuple,
        outline: Optional[tuple] = None,
        width: int = 2,
    ):
        x0, y0, x1, y1 = xy
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    def _draw_text_wrapped(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple,
        x: int,
        y: int,
        max_width: int,
        line_spacing: int = 8,
    ) -> int:
        """Desenha texto com quebra de linha. Retorna a nova posição Y."""
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            bbox = font.getbbox(test)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)

        for line in lines:
            draw.text((x, y), line, font=font, fill=fill)
            bbox = font.getbbox(line)
            y += (bbox[3] - bbox[1]) + line_spacing

        return y

    def _download_image(self, url: str) -> Optional[Image.Image]:
        if not url:
            return None
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            return img
        except Exception:
            return None

    def _make_qr(self, link: str, size: int = 200) -> Image.Image:
        """Gera QR Code nas cores da marca (cyan sobre preto)."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(link)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color=C_CYAN, back_color=C_DARK3).convert("RGBA")
        qr_img = qr_img.resize((size, size), Image.LANCZOS)
        return qr_img

    def _draw_corner_decorations(self, draw: ImageDraw.ImageDraw, pad: int = MARGIN):
        """Cantos decorativos estilo identidade visual descontos.bot."""
        ln = 70   # comprimento das barras
        th = 5    # espessura

        c = (*C_CYAN, 180)
        # Topo esquerdo
        draw.rectangle([pad, pad, pad + ln, pad + th], fill=c)
        draw.rectangle([pad, pad, pad + th, pad + ln], fill=c)
        # Topo direito
        draw.rectangle([STORY_W - pad - ln, pad, STORY_W - pad, pad + th], fill=c)
        draw.rectangle([STORY_W - pad - th, pad, STORY_W - pad, pad + ln], fill=c)
        # Baixo esquerdo
        draw.rectangle([pad, STORY_H - pad - th, pad + ln, STORY_H - pad], fill=c)
        draw.rectangle([pad, STORY_H - pad - ln, pad + th, STORY_H - pad], fill=c)
        # Baixo direito
        draw.rectangle([STORY_W - pad - ln, STORY_H - pad - th, STORY_W - pad, STORY_H - pad], fill=c)
        draw.rectangle([STORY_W - pad - th, STORY_H - pad - ln, STORY_W - pad, STORY_H - pad], fill=c)

    def _draw_grid(self, img: Image.Image):
        """Grid lines sutis estilo identidade visual."""
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        step = 270
        color = (*C_CYAN, 18)  # ~7% opacity
        for x in range(0, STORY_W, step):
            d.line([(x, 0), (x, STORY_H)], fill=color, width=1)
        for y in range(0, STORY_H, step):
            d.line([(0, y), (STORY_W, y)], fill=color, width=1)
        return Image.alpha_composite(img.convert("RGBA"), overlay)

    def _draw_decorative_circles(self, overlay: Image.Image):
        """Círculos decorativos semi-transparentes (cantos opostos)."""
        d = ImageDraw.Draw(overlay)
        # Canto superior direito — cyan
        for r, a in [(280, 12), (180, 12)]:
            d.ellipse([STORY_W - r, -r, STORY_W + r, r], fill=(*C_CYAN, a))
        # Canto inferior esquerdo — amarelo
        for r, a in [(240, 10), (150, 10)]:
            d.ellipse([-r, STORY_H - r, r, STORY_H + r], fill=(*C_YELLOW, a))

    # ── Geração principal ────────────────────────────────────────────────────

    def generate(self, oferta: dict) -> Image.Image:
        nome      = oferta.get("nome", "Produto")
        preco     = oferta.get("preco", 0.0)
        preco_ori = oferta.get("preco_original", preco)
        desc_pct  = oferta.get("desconto_pct", 0)
        frete     = oferta.get("frete_gratis", False)
        img_url   = oferta.get("imagem", "")
        link      = oferta.get("link_afiliado") or oferta.get("link_direto", "")

        # ── Canvas base ──────────────────────────────────────────────────────
        canvas = Image.new("RGB", (STORY_W, STORY_H), C_DARK)
        canvas = self._draw_grid(canvas).convert("RGB")

        # overlay transparente para círculos decorativos
        overlay = Image.new("RGBA", (STORY_W, STORY_H), (0, 0, 0, 0))
        self._draw_decorative_circles(overlay)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(canvas)
        self._draw_corner_decorations(draw)

        # Linha topo e fundo
        draw.rectangle([MARGIN, MARGIN + 10, STORY_W - MARGIN, MARGIN + 13], fill=(*C_CYAN, 100))
        draw.rectangle([MARGIN, STORY_H - MARGIN - 13, STORY_W - MARGIN, STORY_H - MARGIN - 10], fill=(*C_CYAN, 100))

        y = SAFE_TOP

        # ── Badge topo: "BOT ALERTA" ─────────────────────────────────────────
        badge_text = ">> ALERTA DO BOT" if desc_pct < 50 else "!! OFERTA IMPERDIVEL"
        badge_font = self.fonts["mono_bold"][28]
        b_bbox = badge_font.getbbox(badge_text)
        b_w = b_bbox[2] - b_bbox[0] + 48
        b_h = b_bbox[3] - b_bbox[1] + 24
        b_x = (STORY_W - b_w) // 2
        draw.rounded_rectangle([b_x, y, b_x + b_w, y + b_h], radius=24, fill=C_CYAN)
        draw.text((b_x + 24, y + 12), badge_text, font=badge_font, fill=C_DARK)
        y += b_h + 36

        # ── Imagem do produto ────────────────────────────────────────────────
        prod_img = self._download_image(img_url)
        prod_area_h = 480
        prod_area_w = STORY_W - MARGIN * 2

        prod_bg = Image.new("RGB", (prod_area_w, prod_area_h), C_DARK3)
        # borda arredondada
        mask = Image.new("L", prod_bg.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, prod_area_w - 1, prod_area_h - 1], radius=32, fill=255)

        if prod_img:
            # Redimensiona mantendo proporção
            prod_img = prod_img.convert("RGBA")
            prod_img.thumbnail((prod_area_w - 60, prod_area_h - 60), Image.LANCZOS)
            p_x = (prod_area_w - prod_img.width) // 2
            p_y = (prod_area_h - prod_img.height) // 2
            prod_bg.paste(prod_img, (p_x, p_y), prod_img)

        prod_bg.putalpha(mask)
        canvas.paste(prod_bg, (MARGIN, y), prod_bg)
        y += prod_area_h + 32

        # ── Badge de desconto ────────────────────────────────────────────────
        disc_color = C_YELLOW if desc_pct < 50 else (*C_RED_BADGE,)
        disc_text  = f"  {desc_pct}% OFF  "
        disc_font  = self.fonts["mono_bold"][48]
        d_bbox = disc_font.getbbox(disc_text)
        d_w = d_bbox[2] - d_bbox[0] + 32
        d_h = d_bbox[3] - d_bbox[1] + 24
        draw.rounded_rectangle([MARGIN, y, MARGIN + d_w, y + d_h], radius=14, fill=disc_color)
        draw.text((MARGIN + 16, y + 12), disc_text.strip(), font=disc_font, fill=C_DARK)
        y += d_h + 28

        # ── Nome do produto ──────────────────────────────────────────────────
        nome_font = self.fonts["grotesk_bold"][48]
        nome_curto = textwrap.shorten(nome, width=55, placeholder="...")
        y = self._draw_text_wrapped(draw, nome_curto, nome_font, C_WHITE, MARGIN, y, CONTENT_W, line_spacing=10)
        y += 24

        # ── Preços ───────────────────────────────────────────────────────────
        # Preço original riscado
        if preco_ori > preco:
            ori_font = self.fonts["mono_reg"][28]
            ori_text = f"De R$ {preco_ori:,.2f}".replace(",", ".")
            draw.text((MARGIN, y), ori_text, font=ori_font, fill=C_MUTED)
            ori_bbox = ori_font.getbbox(ori_text)
            ori_h = ori_bbox[3] - ori_bbox[1]
            mid_y = y + ori_h // 2
            draw.line([(MARGIN, mid_y), (MARGIN + ori_bbox[2], mid_y)], fill=C_MUTED, width=2)
            y += ori_h + 12

        # Preço atual
        preco_font = self.fonts["mono_bold"][80]
        preco_text = f"R$ {preco:,.2f}".replace(",", ".")
        draw.text((MARGIN, y), preco_text, font=preco_font, fill=C_YELLOW)
        p_bbox = preco_font.getbbox(preco_text)
        y += (p_bbox[3] - p_bbox[1]) + 28

        # ── Frete grátis ─────────────────────────────────────────────────────
        if frete:
            fr_font = self.fonts["mono_bold"][28]
            fr_text = "FRETE GRATIS"
            fr_bbox = fr_font.getbbox(fr_text)
            fr_w = fr_bbox[2] - fr_bbox[0] + 40
            fr_h = fr_bbox[3] - fr_bbox[1] + 20
            draw.rounded_rectangle([MARGIN, y, MARGIN + fr_w, y + fr_h], radius=10, fill=C_CYAN_DIM)
            draw.text((MARGIN + 20, y + 10), fr_text, font=fr_font, fill=C_DARK)
            y += fr_h + 28

        # ── QR Code + link ───────────────────────────────────────────────────
        qr_size = 200
        qr_img = self._make_qr(link, size=qr_size)

        # Fundo do QR (card arredondado)
        qr_card_pad = 16
        qr_card_w = qr_size + qr_card_pad * 2
        qr_card_h = qr_size + qr_card_pad * 2 + 48  # espaço para texto abaixo
        qr_label_font = self.fonts["mono_reg"][22]
        qr_label = "Escaneie para comprar"

        # Card de fundo do QR
        draw.rounded_rectangle(
            [MARGIN, y, MARGIN + qr_card_w, y + qr_card_h],
            radius=18, fill=C_DARK3, outline=C_CYAN_DIM, width=2
        )
        canvas.paste(qr_img, (MARGIN + qr_card_pad, y + qr_card_pad), qr_img)
        draw.text((MARGIN + qr_card_pad, y + qr_size + qr_card_pad + 8), qr_label, font=qr_label_font, fill=C_MUTED)

        y += qr_card_h + 20

        # ── Avatar + nome do bot ──────────────────────────────────────────────
        avatar_y = STORY_H - SAFE_BOT + 50
        avatar_x = MARGIN

        if self.avatar:
            # Máscara circular para o avatar
            av_mask = Image.new("L", self.avatar.size, 0)
            ImageDraw.Draw(av_mask).ellipse([0, 0, 79, 79], fill=255)
            av_rgba = self.avatar.copy()
            av_rgba.putalpha(av_mask)
            canvas.paste(av_rgba, (avatar_x, avatar_y), av_rgba)
            text_x = avatar_x + 90
        else:
            text_x = avatar_x

        name_font_big   = self.fonts["mono_bold"][36]
        name_font_small = self.fonts["mono_reg"][22]
        draw.text((text_x, avatar_y + 8),  "descontos.bot", font=name_font_big, fill=C_CYAN)
        draw.text((text_x, avatar_y + 52), "@descontos.bot", font=name_font_small, fill=C_MUTED)

        return canvas

    def save(self, oferta: dict, dest_dir: Path) -> Path:
        img = self.generate(oferta)
        safe_id = oferta.get("id", "oferta").replace("/", "_")
        filepath = dest_dir / f"{safe_id}.png"
        img.save(filepath, format="PNG", optimize=True)
        return filepath


# ─── Preview HTML ─────────────────────────────────────────────────────────────

class PreviewGenerator:
    """Gera um preview.html local para visualizar todos os posts gerados."""

    def generate(self, ofertas: list[dict], output_dir: Path) -> Path:
        rows = []
        for o in ofertas:
            safe_id = o.get("id", "oferta").replace("/", "_")
            txt_path = f"whatsapp/{safe_id}.txt"
            img_path = f"stories/{safe_id}.png"
            nome = o.get("nome", "")[:60]
            preco = o.get("preco", 0)
            disc = o.get("desconto_pct", 0)
            link = o.get("link_afiliado") or o.get("link_direto", "#")

            preco_fmt = f"R$ {preco:,.2f}".replace(",", ".")
            rows.append(f"""
            <div class="card">
              <div class="badge">{disc}% OFF</div>
              <img class="story-thumb" src="{img_path}" alt="{nome}" loading="lazy">
              <div class="info">
                <div class="name">{nome}</div>
                <div class="price">{preco_fmt}</div>
                <div class="actions">
                  <a href="{link}" target="_blank" class="btn btn-buy">Ver Oferta</a>
                  <a href="{txt_path}" download class="btn btn-wa">WhatsApp .txt</a>
                  <a href="{img_path}" download class="btn btn-dl">Baixar Story</a>
                </div>
              </div>
            </div>""")


        now = datetime.now(timezone(BRT_OFFSET)).strftime("%d/%m/%Y %H:%M BRT")
        html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>descontos.bot — Preview de Posts</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{
  --dark:#0D0F14;--dark2:#161A22;--dark3:#1E2330;
  --cyan:#00C9B1;--yellow:#FFE14D;--white:#F4F7FF;--muted:#8A93A8;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Space Grotesk',sans-serif;background:var(--dark);color:var(--white);padding:2rem 1rem}}
header{{text-align:center;margin-bottom:2.5rem}}
header h1{{font-family:'Space Mono',monospace;font-size:28px;font-weight:700}}
header h1 span{{color:var(--cyan)}}
header h1 em{{color:var(--yellow);font-style:normal}}
header p{{color:var(--muted);font-size:13px;margin-top:6px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;max-width:1400px;margin:0 auto}}
.card{{background:var(--dark3);border-radius:20px;overflow:hidden;border:1px solid rgba(0,201,177,0.15);transition:transform .2s,box-shadow .2s;position:relative}}
.card:hover{{transform:translateY(-4px);box-shadow:0 12px 40px rgba(0,201,177,0.15)}}
.badge{{position:absolute;top:12px;left:12px;background:var(--yellow);color:var(--dark);font-family:'Space Mono',monospace;font-size:12px;font-weight:700;padding:4px 12px;border-radius:20px;z-index:2}}
.story-thumb{{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;background:var(--dark2)}}
.info{{padding:1rem}}
.name{{font-size:13px;color:var(--muted);margin-bottom:4px;line-height:1.4}}
.price{{font-family:'Space Mono',monospace;font-size:22px;font-weight:700;color:var(--yellow);margin-bottom:12px}}
.actions{{display:flex;flex-wrap:wrap;gap:8px}}
.btn{{font-family:'Space Mono',monospace;font-size:11px;font-weight:700;padding:7px 14px;border-radius:10px;text-decoration:none;display:inline-block;transition:opacity .2s}}
.btn:hover{{opacity:.8}}
.btn-buy{{background:var(--cyan);color:var(--dark)}}
.btn-wa{{background:#25D366;color:#fff}}
.btn-dl{{background:var(--dark2);color:var(--cyan);border:1px solid var(--cyan)}}
footer{{text-align:center;color:var(--muted);font-size:12px;margin-top:3rem;font-family:'Space Mono',monospace}}
</style>
</head>
<body>
<header>
  <h1>descontos<span>.bot</span> — Preview de Posts <em>({len(ofertas)} ofertas)</em></h1>
  <p>Gerado em {now} • Clique para baixar ou ver a oferta</p>
</header>
<div class="grid">
{''.join(rows)}
</div>
<footer>🤖 descontos.bot — Gerador de Posts Fase 2</footer>
</body>
</html>"""

        filepath = output_dir / "preview.html"
        filepath.write_text(html, encoding="utf-8")
        return filepath


# ─── Post Manager (Orquestrador) ─────────────────────────────────────────────

class PostManager:
    def __init__(self):
        print("📁 Configurando diretórios de saída...")
        WA_DIR.mkdir(parents=True, exist_ok=True)
        STORIES_DIR.mkdir(parents=True, exist_ok=True)

        print("🔤 Verificando fontes...")
        font_paths = ensure_fonts()
        fonts = load_fonts(font_paths)

        self.wa_gen      = WhatsAppPostGenerator()
        self.story_gen   = InstagramStoryGenerator(fonts, avatar_path=AVATAR_FILE)
        self.preview_gen = PreviewGenerator()

    def load_ofertas(self) -> list[dict]:
        if not OFERTAS_FILE.exists():
            print(f"❌ Arquivo não encontrado: {OFERTAS_FILE}")
            return []
        with open(OFERTAS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        ofertas = data.get("ofertas", [])
        print(f"📋 {len(ofertas)} ofertas carregadas do {OFERTAS_FILE.name}")
        return ofertas

    def run(self, limit: Optional[int] = None) -> None:
        print("\n🤖 descontos.bot — Gerador de Posts — Fase 2")
        print("=" * 50)

        ofertas = self.load_ofertas()
        if not ofertas:
            return

        if limit:
            ofertas = ofertas[:limit]
            print(f"⚠️  Limitando a {limit} ofertas para este run.")

        total = len(ofertas)
        print(f"\n🚀 Gerando posts para {total} ofertas...\n")

        for i, oferta in enumerate(ofertas, 1):
            nome = textwrap.shorten(oferta.get("nome", "?"), width=45, placeholder="...")
            print(f"  [{i:3d}/{total}] {nome}")

            # WhatsApp
            try:
                wa_path = self.wa_gen.save(oferta, WA_DIR)
            except Exception as e:
                print(f"         ⚠️  WhatsApp erro: {e}")

            # Story
            try:
                story_path = self.story_gen.save(oferta, STORIES_DIR)
                print(f"         ✅ Story gerado: {story_path.name}")
            except Exception as e:
                print(f"         ❌ Story erro: {e}")

        # Preview HTML
        print("\n🌐 Gerando preview.html...")
        preview_path = self.preview_gen.generate(ofertas, OUTPUT_DIR)
        print(f"   ✅ Preview: {preview_path}")

        print(f"\n✨ Concluído!")
        print(f"   📁 Pasta de saída: {OUTPUT_DIR}")
        print(f"   💬 WhatsApp .txt : {WA_DIR}")
        print(f"   📸 Stories .png  : {STORIES_DIR}")
        print(f"   🌐 Preview HTML  : {preview_path}")
        print(f"\n   👉 Abra o preview.html no navegador para escolher seus posts!")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gerador de Posts descontos.bot")
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Limitar a N ofertas (útil para testar). Ex: --limit 5",
    )
    args = parser.parse_args()

    manager = PostManager()
    manager.run(limit=args.limit)
