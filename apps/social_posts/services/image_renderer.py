import hashlib
import io
import logging
import re
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests
from django.conf import settings
from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont

from apps.offers.models import Offer
from apps.social_posts.services.link_builder import build_instagram_tracked_url


logger = logging.getLogger(__name__)


STORY_W = 1080
STORY_H = 1920
FEED_W = 1080
FEED_H = 1080
SAFE_TOP = 220
SAFE_BOT = 260
MARGIN = 60

# Design System — paleta oficial em design_system/refs/design_system.html.
C_DARK = (13, 15, 20)
C_DARK2 = (22, 26, 34)
C_DARK3 = (30, 35, 48)
C_CYAN = (0, 201, 177)
C_CYAN_DIM = (0, 158, 141)
C_YELLOW = (255, 225, 77)
C_WHITE = (244, 247, 255)
C_MUTED = (138, 147, 168)
C_RED_BADGE = (255, 77, 77)

BRT = timezone(timedelta(hours=-3))

INSTAGRAM_MEDIA_SUBDIR = 'instagram'
INVALID_LINK_FRAGMENTS = ('example.com', 'placeholder', 'localhost')

_EMOJI_RE = re.compile(
    '['
    '\U0001F300-\U0001FAFF'
    '\U00002600-\U000027BF'
    '\U0001F1E0-\U0001F1FF'
    ']+',
    flags=re.UNICODE,
)


@dataclass(frozen=True)
class RenderedAsset:
    path: str
    sidecar_path: str | None = None


# ── Public API ───────────────────────────────────────────────────────────────


def render_story_asset(offer: Offer, link: str | None = None) -> RenderedAsset:
    short_id = _short_marketplace_offer_id(offer)
    marketplace_code = (offer.marketplace.code or 'unknown').lower()

    image_url = (offer.image_url or '').strip()
    if not image_url:
        logger.error(
            'instagram_story.skip reason=missing_image offer_id=%s marketplace=%s short_id=%s',
            offer.id, marketplace_code, short_id,
        )
        raise RuntimeError(
            f'Oferta #{offer.id} ({marketplace_code}/{short_id}) sem image_url — Story não pode ser gerado.',
        )

    product_image = _download_image(image_url)
    if product_image is None:
        logger.error(
            'instagram_story.skip reason=image_download_failed offer_id=%s url=%s',
            offer.id, image_url,
        )
        raise RuntimeError(
            f'Oferta #{offer.id} imagem indisponível em {image_url} — Story não pode ser gerado.',
        )

    tracked_url = link or build_instagram_tracked_url(offer, 'story')
    if not _is_valid_publication_link(tracked_url):
        logger.error(
            'instagram_story.skip reason=invalid_link offer_id=%s link=%r',
            offer.id, tracked_url,
        )
        raise RuntimeError(
            f'Oferta #{offer.id} link de divulgação inválido ({tracked_url!r}) — Story não pode ser gerado.',
        )

    canvas = _build_story_image(offer, product_image)
    image_path = _resolve_unique_output_path(offer, kind='stories', suffix='story', ext='png')
    canvas.save(image_path, format='PNG', optimize=True)

    sidecar_path = image_path.with_suffix('.txt')
    _write_sidecar_txt(sidecar_path, offer=offer, link=tracked_url)

    logger.info(
        'instagram_story.rendered offer_id=%s marketplace=%s short_id=%s image=%s sidecar=%s',
        offer.id, marketplace_code, short_id,
        image_path.as_posix(), sidecar_path.as_posix(),
    )
    return RenderedAsset(path=str(image_path), sidecar_path=str(sidecar_path))


def render_feed_asset(offer: Offer, suffix: str = 'feed') -> RenderedAsset:
    return _legacy_write_asset(
        offer, suffix=suffix, width=FEED_W, height=FEED_H,
        badge='>> ALERTA DO BOT', kind='feed',
    )


def render_carousel_assets(offers: list[Offer]) -> list[RenderedAsset]:
    return [
        _legacy_write_asset(
            offer, suffix=f'carousel-{index}', width=FEED_W, height=FEED_H,
            badge=f'OFERTA {index}', kind='carousel',
        )
        for index, offer in enumerate(offers, start=1)
    ]


# ── Naming helpers ───────────────────────────────────────────────────────────


def build_short_asset_basename(offer: Offer, suffix: str) -> str:
    marketplace_code = re.sub(r'[^a-z0-9]', '', (offer.marketplace.code or 'unknown').lower()) or 'unknown'
    short_id = _short_marketplace_offer_id(offer)
    safe_suffix = re.sub(r'[^a-z0-9-]', '', suffix.lower()) or 'asset'
    return f'{marketplace_code}_{short_id}_{safe_suffix}'


def _short_marketplace_offer_id(offer: Offer) -> str:
    code = (offer.marketplace.code or '').lower()
    candidate = ''
    if code == 'amazon':
        candidate = (offer.asin or offer.external_id or '').strip()
    else:
        candidate = (offer.external_id or offer.asin or '').strip()

    sanitized = re.sub(r'[^A-Za-z0-9]', '', candidate).lower()
    if sanitized:
        return sanitized

    if offer.pk:
        return f'offer{offer.pk}'
    if offer.slug:
        return re.sub(r'[^a-z0-9]', '', slugify(offer.slug))[:20] or 'oferta'
    seed = (offer.product_url or offer.title or 'oferta').encode('utf-8')
    return hashlib.md5(seed).hexdigest()[:10]


def _resolve_unique_output_path(offer: Offer, kind: str, suffix: str, ext: str) -> Path:
    base_dir = Path(settings.MEDIA_ROOT) / INSTAGRAM_MEDIA_SUBDIR / kind
    base_dir.mkdir(parents=True, exist_ok=True)
    basename = build_short_asset_basename(offer, suffix)
    primary = base_dir / f'{basename}.{ext}'
    if not primary.exists() and not primary.with_suffix('.txt').exists():
        return primary

    n = 2
    while True:
        candidate = base_dir / f'{basename}-{n}.{ext}'
        if not candidate.exists() and not candidate.with_suffix('.txt').exists():
            logger.warning(
                'instagram_story.name_conflict offer_id=%s base=%s -> %s',
                offer.id, primary.name, candidate.name,
            )
            return candidate
        n += 1


# ── Sidecar .txt ─────────────────────────────────────────────────────────────


def _is_valid_publication_link(link: str | None) -> bool:
    if not link or not isinstance(link, str):
        return False
    value = link.strip()
    if not value:
        return False
    if not (value.startswith('http://') or value.startswith('https://')):
        return False
    lowered = value.lower()
    return not any(fragment in lowered for fragment in INVALID_LINK_FRAGMENTS)


def _write_sidecar_txt(path: Path, offer: Offer, link: str) -> None:
    title_short = textwrap.shorten(
        _clean_title(offer.title or '') or 'Produto',
        width=80,
        placeholder='...',
    )
    marketplace_name = offer.marketplace.name or offer.marketplace.code or 'Marketplace'
    timestamp = datetime.now(BRT).strftime('%Y-%m-%d %H:%M')
    body = (
        f'Produto: {title_short}\n'
        f'Marketplace: {marketplace_name}\n'
        f'Link: {link}\n'
        f'Gerado em: {timestamp}\n'
    )
    path.write_text(body, encoding='utf-8')


# ── Story image build ────────────────────────────────────────────────────────


def _build_story_image(offer: Offer, product_image: Image.Image) -> Image.Image:
    canvas = Image.new('RGB', (STORY_W, STORY_H), C_DARK)
    draw = ImageDraw.Draw(canvas)

    _draw_story_kicker(draw, y=250)
    _draw_story_badges(draw, offer, y=340)
    _paste_product_card(canvas, product_image, x=MARGIN, y=470, w=STORY_W - MARGIN * 2, h=720)
    title_end = _draw_story_title(draw, offer.title or 'Produto', x=MARGIN, y=1220)
    _draw_story_prices(draw, offer, x=MARGIN, y=title_end + 24)
    _draw_story_cta(draw, x=MARGIN, y=1640)
    _draw_story_signature(draw, x=MARGIN, y=1770)
    return canvas


def _draw_story_kicker(draw: ImageDraw.ImageDraw, y: int) -> None:
    label = 'achado do bot'
    font = _font('regular', 28)
    label_bbox = draw.textbbox((0, 0), label, font=font)
    label_w = label_bbox[2] - label_bbox[0]
    dot_size = 12
    gap = 16
    total_w = dot_size + gap + label_w
    start_x = (STORY_W - total_w) // 2
    draw.ellipse(
        [start_x, y + 12, start_x + dot_size, y + 12 + dot_size],
        fill=C_CYAN,
    )
    draw.text((start_x + dot_size + gap, y), label, font=font, fill=C_MUTED)

    line_w = 240
    line_x = (STORY_W - line_w) // 2
    line_y = y + 60
    draw.rectangle([line_x, line_y, line_x + line_w, line_y + 2], fill=C_CYAN_DIM)


def _draw_story_badges(draw: ImageDraw.ImageDraw, offer: Offer, y: int) -> None:
    discount = int(offer.discount_pct or Decimal('0'))
    if discount > 0:
        text = f'{discount}% OFF'
        font = _font('bold', 52)
        bbox = draw.textbbox((0, 0), text, font=font)
        pill_w = bbox[2] - bbox[0] + 56
        pill_h = bbox[3] - bbox[1] + 28
        fill = C_RED_BADGE if discount >= 50 else C_YELLOW
        draw.rounded_rectangle([MARGIN, y, MARGIN + pill_w, y + pill_h], radius=18, fill=fill)
        draw.text((MARGIN + 28, y + 12), text, font=font, fill=C_DARK)

    marketplace_label = (offer.marketplace.name or offer.marketplace.code or '').strip()
    if marketplace_label:
        mkt_font = _font('bold', 26)
        bbox = draw.textbbox((0, 0), marketplace_label, font=mkt_font)
        m_w = bbox[2] - bbox[0] + 40
        m_h = bbox[3] - bbox[1] + 22
        m_x = STORY_W - MARGIN - m_w
        m_y = y + 14
        draw.rounded_rectangle(
            [m_x, m_y, m_x + m_w, m_y + m_h],
            radius=14, fill=C_DARK3, outline=C_CYAN_DIM, width=2,
        )
        draw.text((m_x + 20, m_y + 10), marketplace_label, font=mkt_font, fill=C_CYAN)


def _paste_product_card(
    canvas: Image.Image,
    product_image: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    card = Image.new('RGB', (w, h), C_DARK2)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=36, fill=255)

    rgba = product_image.convert('RGBA')
    rgba.thumbnail((w - 80, h - 80), Image.LANCZOS)
    px = (w - rgba.width) // 2
    py = (h - rgba.height) // 2
    card.paste(rgba, (px, py), rgba)
    card.putalpha(mask)
    canvas.paste(card, (x, y), card)


def _draw_story_title(draw: ImageDraw.ImageDraw, raw_title: str, x: int, y: int) -> int:
    cleaned = _clean_title(raw_title)
    cleaned = textwrap.shorten(cleaned, width=60, placeholder='...')
    font = _font('bold', 56)
    return _draw_text_wrapped(
        draw, cleaned, font, C_WHITE, x, y,
        max_width=STORY_W - 2 * MARGIN,
        line_spacing=12, max_lines=2,
    )


def _draw_story_prices(draw: ImageDraw.ImageDraw, offer: Offer, x: int, y: int) -> None:
    if offer.original_price and offer.original_price > offer.current_price:
        original_font = _font('regular', 36)
        original_text = f'De R$ {_format_money(offer.original_price)}'
        draw.text((x, y), original_text, font=original_font, fill=C_MUTED)
        bbox = draw.textbbox((x, y), original_text, font=original_font)
        mid_y = y + (bbox[3] - bbox[1]) // 2 + 4
        draw.line([(x, mid_y), (bbox[2], mid_y)], fill=C_MUTED, width=3)
        y += (bbox[3] - bbox[1]) + 14

    price_font = _font('bold', 140)
    price_text = f'R$ {_format_money(offer.current_price)}'
    draw.text((x, y), price_text, font=price_font, fill=C_YELLOW)


def _draw_story_cta(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    text = 'toque no link acima'
    font = _font('bold', 30)
    bbox = draw.textbbox((0, 0), text, font=font)
    pill_w = bbox[2] - bbox[0] + 64
    pill_h = bbox[3] - bbox[1] + 32
    draw.rounded_rectangle([x, y, x + pill_w, y + pill_h], radius=22, fill=C_CYAN)
    draw.text((x + 32, y + 16), text, font=font, fill=C_DARK)


def _draw_story_signature(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    name_font = _font('bold', 30)
    handle_font = _font('regular', 22)
    draw.text((x, y), 'descontos.bot', font=name_font, fill=C_CYAN)
    draw.text((x, y + 44), '@descontos.bot', font=handle_font, fill=C_MUTED)

    timestamp = datetime.now(BRT).strftime('%d.%m %Hh%M')
    ts_font = _font('regular', 22)
    ts_bbox = draw.textbbox((0, 0), timestamp, font=ts_font)
    ts_x = STORY_W - MARGIN - (ts_bbox[2] - ts_bbox[0])
    draw.text((ts_x, y + 22), timestamp, font=ts_font, fill=C_MUTED)


# ── Legacy renderer (feed/carousel — mantém visual atual) ───────────────────


def _legacy_write_asset(
    offer: Offer,
    suffix: str,
    width: int,
    height: int,
    badge: str,
    kind: str,
) -> RenderedAsset:
    output_dir = Path(settings.MEDIA_ROOT) / INSTAGRAM_MEDIA_SUBDIR / kind
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = build_short_asset_basename(offer, suffix)
    path = _resolve_unique_legacy_path(output_dir, basename, 'png')
    image = _build_legacy_image(offer, width, height, badge)
    image.save(path, format='PNG', optimize=True)
    logger.info(
        'instagram_%s.rendered offer_id=%s short_id=%s image=%s',
        kind, offer.id, _short_marketplace_offer_id(offer), path.as_posix(),
    )
    return RenderedAsset(path=str(path))


def _resolve_unique_legacy_path(base_dir: Path, basename: str, ext: str) -> Path:
    primary = base_dir / f'{basename}.{ext}'
    if not primary.exists():
        return primary
    n = 2
    while True:
        candidate = base_dir / f'{basename}-{n}.{ext}'
        if not candidate.exists():
            return candidate
        n += 1


def _build_legacy_image(offer: Offer, width: int, height: int, badge: str) -> Image.Image:
    canvas = Image.new('RGB', (width, height), C_DARK)
    canvas = _draw_grid(canvas)

    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    _draw_decorative_circles(overlay, width, height)
    canvas = Image.alpha_composite(canvas.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(canvas)
    _draw_corner_decorations(draw, width, height)
    draw.rectangle([MARGIN, MARGIN + 10, width - MARGIN, MARGIN + 13], fill=(*C_CYAN, 100))
    draw.rectangle([MARGIN, height - MARGIN - 13, width - MARGIN, height - MARGIN - 10], fill=(*C_CYAN, 100))

    y = 120
    y = _draw_centered_badge(draw, badge, y, width)
    y = _paste_legacy_product(canvas, offer, MARGIN, y, width - MARGIN * 2, 350) + 24
    y = _draw_legacy_discount(draw, offer, MARGIN, y) + 20
    y = _draw_legacy_title(draw, offer.title or 'Produto', MARGIN, y, width - MARGIN * 2, 40) + 14
    _draw_legacy_prices(draw, offer, MARGIN, y, 62)
    _draw_story_signature(draw, MARGIN, height - 150)
    return canvas


def _draw_centered_badge(draw: ImageDraw.ImageDraw, text: str, y: int, width: int) -> int:
    font = _font('bold', 28)
    bbox = draw.textbbox((0, 0), text, font=font)
    badge_w = bbox[2] - bbox[0] + 48
    badge_h = bbox[3] - bbox[1] + 24
    x = (width - badge_w) // 2
    draw.rounded_rectangle([x, y, x + badge_w, y + badge_h], radius=24, fill=C_CYAN)
    draw.text((x + 24, y + 12), text, font=font, fill=C_DARK)
    return y + badge_h + 36


def _paste_legacy_product(
    canvas: Image.Image,
    offer: Offer,
    x: int,
    y: int,
    width: int,
    height: int,
) -> int:
    product_image = _download_image(offer.image_url)
    product_bg = Image.new('RGB', (width, height), C_DARK3)
    mask = Image.new('L', product_bg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, height - 1], radius=32, fill=255)

    if product_image:
        rgba = product_image.convert('RGBA')
        rgba.thumbnail((width - 60, height - 60), Image.LANCZOS)
        px = (width - rgba.width) // 2
        py = (height - rgba.height) // 2
        product_bg.paste(rgba, (px, py), rgba)

    product_bg.putalpha(mask)
    canvas.paste(product_bg, (x, y), product_bg)
    return y + height


def _draw_legacy_discount(draw: ImageDraw.ImageDraw, offer: Offer, x: int, y: int) -> int:
    discount = int(offer.discount_pct or Decimal('0'))
    fill = C_YELLOW if discount < 50 else C_RED_BADGE
    text = f'{discount}% OFF'
    font = _font('bold', 48)
    bbox = draw.textbbox((0, 0), text, font=font)
    badge_w = bbox[2] - bbox[0] + 64
    badge_h = bbox[3] - bbox[1] + 24
    draw.rounded_rectangle([x, y, x + badge_w, y + badge_h], radius=14, fill=fill)
    draw.text((x + 32, y + 12), text, font=font, fill=C_DARK)
    return y + badge_h


def _draw_legacy_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    x: int,
    y: int,
    max_width: int,
    size: int,
) -> int:
    font = _font('bold', size)
    cleaned = _clean_title(title)
    cleaned = textwrap.shorten(cleaned, width=64, placeholder='...')
    return _draw_text_wrapped(draw, cleaned, font, C_WHITE, x, y, max_width, line_spacing=10, max_lines=3)


def _draw_legacy_prices(draw: ImageDraw.ImageDraw, offer: Offer, x: int, y: int, size: int) -> int:
    if offer.original_price and offer.original_price > offer.current_price:
        original_font = _font('regular', max(24, size // 3))
        original_text = f'De R$ {_format_money(offer.original_price)}'
        draw.text((x, y), original_text, font=original_font, fill=C_MUTED)
        bbox = draw.textbbox((x, y), original_text, font=original_font)
        mid_y = y + (bbox[3] - bbox[1]) // 2
        draw.line([(x, mid_y), (bbox[2], mid_y)], fill=C_MUTED, width=2)
        y += (bbox[3] - bbox[1]) + 12

    price_font = _font('bold', size)
    price_text = f'R$ {_format_money(offer.current_price)}'
    draw.text((x, y), price_text, font=price_font, fill=C_YELLOW)
    bbox = draw.textbbox((x, y), price_text, font=price_font)
    return y + (bbox[3] - bbox[1])


# ── Shared drawing helpers ───────────────────────────────────────────────────


def _draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    x: int,
    y: int,
    max_width: int,
    line_spacing: int = 8,
    max_lines: int = 4,
) -> int:
    words = text.split()
    lines: list[str] = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    visible = lines[:max_lines]
    if len(lines) > max_lines and visible:
        visible[-1] = visible[-1].rstrip(' .,') + '...'

    for line in visible:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing

    return y


def _download_image(url: str | None) -> Image.Image | None:
    if not url:
        return None
    upgraded = _upgrade_image_url(url)
    for candidate in (upgraded, url) if upgraded != url else (url,):
        try:
            response = requests.get(candidate, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content)).convert('RGBA')
        except Exception:
            continue
    return _download_image_with_curl(url)


def _upgrade_image_url(url: str) -> str:
    """Eleva URLs de thumbnail de marketplaces para resolução maior antes do download."""
    if any(host in url for host in ('media-amazon.com', 'images-amazon.com', 'ssl-images-amazon.com')):
        return re.sub(r'\._[A-Z0-9_]+_\.', '._UL1200_.', url)
    return url


def _download_image_with_curl(url: str) -> Image.Image | None:
    try:
        result = subprocess.run(
            [
                'curl', '-L', '--silent', '--show-error',
                '--max-time', '10',
                '--user-agent', 'Mozilla/5.0',
                url,
            ],
            check=True,
            capture_output=True,
        )
        return Image.open(io.BytesIO(result.stdout)).convert('RGBA')
    except Exception:
        return None


def _draw_corner_decorations(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    line_length = 70
    thickness = 5
    color = (*C_CYAN, 180)
    draw.rectangle([MARGIN, MARGIN, MARGIN + line_length, MARGIN + thickness], fill=color)
    draw.rectangle([MARGIN, MARGIN, MARGIN + thickness, MARGIN + line_length], fill=color)
    draw.rectangle([width - MARGIN - line_length, MARGIN, width - MARGIN, MARGIN + thickness], fill=color)
    draw.rectangle([width - MARGIN - thickness, MARGIN, width - MARGIN, MARGIN + line_length], fill=color)
    draw.rectangle([MARGIN, height - MARGIN - thickness, MARGIN + line_length, height - MARGIN], fill=color)
    draw.rectangle([MARGIN, height - MARGIN - line_length, MARGIN + thickness, height - MARGIN], fill=color)
    draw.rectangle([width - MARGIN - line_length, height - MARGIN - thickness, width - MARGIN, height - MARGIN], fill=color)
    draw.rectangle([width - MARGIN - thickness, height - MARGIN - line_length, width - MARGIN, height - MARGIN], fill=color)


def _draw_grid(image: Image.Image) -> Image.Image:
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = 270
    color = (*C_CYAN, 18)
    for x in range(0, image.width, step):
        draw.line([(x, 0), (x, image.height)], fill=color, width=1)
    for y in range(0, image.height, step):
        draw.line([(0, y), (image.width, y)], fill=color, width=1)
    return Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')


def _draw_decorative_circles(overlay: Image.Image, width: int, height: int) -> None:
    draw = ImageDraw.Draw(overlay)
    for radius, alpha in [(280, 12), (180, 12)]:
        draw.ellipse([width - radius, -radius, width + radius, radius], fill=(*C_CYAN, alpha))
    for radius, alpha in [(240, 10), (150, 10)]:
        draw.ellipse([-radius, height - radius, radius, height + radius], fill=(*C_YELLOW, alpha))


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if weight == 'bold' else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if weight == 'bold' else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _format_money(value: Decimal) -> str:
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _clean_title(raw: str) -> str:
    cleaned = raw or ''
    cleaned = re.sub(
        r'^\s*an[uú]ncio\s+patrocinado\s*[\-–—:]\s*',
        '',
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _EMOJI_RE.sub('', cleaned)
    cleaned = re.sub(r'[!]{1,}', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    words = cleaned.split()
    upper_words = [w for w in words if len(w) > 3 and w.isupper()]
    if len(upper_words) > 1:
        cleaned = ' '.join(
            w.title() if len(w) > 3 and w.isupper() else w
            for w in words
        )
    return cleaned
