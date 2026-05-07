import io
import subprocess
import textwrap
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import requests
from django.conf import settings
from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont

from apps.offers.models import Offer


STORY_W = 1080
STORY_H = 1920
FEED_W = 1080
FEED_H = 1080
SAFE_TOP = 280
SAFE_BOT = 300
MARGIN = 40

C_CYAN = (0, 201, 177)
C_CYAN_DIM = (0, 158, 141)
C_YELLOW = (255, 225, 77)
C_DARK = (13, 15, 20)
C_DARK2 = (22, 26, 34)
C_DARK3 = (30, 35, 48)
C_WHITE = (244, 247, 255)
C_MUTED = (138, 147, 168)
C_RED_BADGE = (255, 77, 77)


@dataclass(frozen=True)
class RenderedAsset:
    path: str


def render_feed_asset(offer: Offer, suffix: str = 'feed') -> RenderedAsset:
    return _write_asset(offer, suffix, FEED_W, FEED_H, '>> ALERTA DO BOT')


def render_story_asset(offer: Offer, suffix: str = 'story') -> RenderedAsset:
    return _write_asset(offer, suffix, STORY_W, STORY_H, '>> ALERTA DO BOT')


def render_carousel_assets(offers: list[Offer]) -> list[RenderedAsset]:
    return [
        _write_asset(offer, f'carousel-{index}', FEED_W, FEED_H, f'OFERTA {index}')
        for index, offer in enumerate(offers, start=1)
    ]


def _write_asset(
    offer: Offer,
    suffix: str,
    width: int,
    height: int,
    badge: str,
) -> RenderedAsset:
    output_dir = Path(settings.MEDIA_ROOT) / 'instagram_posts'
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{offer.id}-{slugify(offer.title)[:80]}-{suffix}.png'
    path = output_dir / filename
    image = _build_image(offer, width, height, badge)
    image.save(path, format='PNG', optimize=True)
    return RenderedAsset(path=str(path))


def _build_image(
    offer: Offer,
    width: int,
    height: int,
    badge: str,
) -> Image.Image:
    canvas = Image.new('RGB', (width, height), C_DARK)
    canvas = _draw_grid(canvas)

    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    _draw_decorative_circles(overlay, width, height)
    canvas = Image.alpha_composite(canvas.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(canvas)
    _draw_corner_decorations(draw, width, height)
    draw.rectangle([MARGIN, MARGIN + 10, width - MARGIN, MARGIN + 13], fill=(*C_CYAN, 100))
    draw.rectangle([MARGIN, height - MARGIN - 13, width - MARGIN, height - MARGIN - 10], fill=(*C_CYAN, 100))

    if height > width:
        _draw_story_content(draw, canvas, offer, badge)
    else:
        _draw_square_content(draw, canvas, offer, badge)

    return canvas


def _draw_story_content(
    draw: ImageDraw.ImageDraw,
    canvas: Image.Image,
    offer: Offer,
    badge: str,
) -> None:
    y = SAFE_TOP
    y = _draw_badge(draw, badge, y, STORY_W)
    y = _draw_product_card(canvas, offer, MARGIN, y, STORY_W - MARGIN * 2, 480) + 32
    y = _draw_discount_badge(draw, offer, MARGIN, y) + 28
    y = _draw_title(draw, offer.title, MARGIN, y, STORY_W - MARGIN * 2, 48) + 24
    _draw_prices(draw, offer, MARGIN, y, 80)
    _draw_brand(draw, MARGIN, STORY_H - SAFE_BOT + 50)


def _draw_square_content(
    draw: ImageDraw.ImageDraw,
    canvas: Image.Image,
    offer: Offer,
    badge: str,
) -> None:
    y = 120
    y = _draw_badge(draw, badge, y, FEED_W)
    y = _draw_product_card(canvas, offer, MARGIN, y, FEED_W - MARGIN * 2, 350) + 24
    y = _draw_discount_badge(draw, offer, MARGIN, y) + 20
    y = _draw_title(draw, offer.title, MARGIN, y, FEED_W - MARGIN * 2, 40) + 14
    _draw_prices(draw, offer, MARGIN, y, 62)
    _draw_brand(draw, MARGIN, FEED_H - 150)


def _draw_badge(draw: ImageDraw.ImageDraw, text: str, y: int, width: int) -> int:
    font = _font('bold', 28)
    bbox = draw.textbbox((0, 0), text, font=font)
    badge_w = bbox[2] - bbox[0] + 48
    badge_h = bbox[3] - bbox[1] + 24
    x = (width - badge_w) // 2
    draw.rounded_rectangle([x, y, x + badge_w, y + badge_h], radius=24, fill=C_CYAN)
    draw.text((x + 24, y + 12), text, font=font, fill=C_DARK)
    return y + badge_h + 36


def _draw_product_card(
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
        product_image = product_image.convert('RGBA')
        product_image.thumbnail((width - 60, height - 60), Image.LANCZOS)
        product_x = (width - product_image.width) // 2
        product_y = (height - product_image.height) // 2
        product_bg.paste(product_image, (product_x, product_y), product_image)

    product_bg.putalpha(mask)
    canvas.paste(product_bg, (x, y), product_bg)
    return y + height


def _draw_discount_badge(draw: ImageDraw.ImageDraw, offer: Offer, x: int, y: int) -> int:
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


def _draw_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    x: int,
    y: int,
    max_width: int,
    size: int,
) -> int:
    font = _font('bold', size)
    title = textwrap.shorten(title, width=64, placeholder='...')
    return _draw_text_wrapped(draw, title, font, C_WHITE, x, y, max_width, line_spacing=10)


def _draw_prices(draw: ImageDraw.ImageDraw, offer: Offer, x: int, y: int, size: int) -> int:
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


def _draw_brand(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    name_font = _font('bold', 36)
    handle_font = _font('regular', 22)
    draw.text((x, y + 8), 'descontos.bot', font=name_font, fill=C_CYAN)
    draw.text((x, y + 52), '@descontos.bot', font=handle_font, fill=C_MUTED)


def _draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    x: int,
    y: int,
    max_width: int,
    line_spacing: int = 8,
) -> int:
    words = text.split()
    lines: list[str] = []
    current = ''
    for word in words:
        test = f'{current} {word}'.strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    for line in lines[:4]:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing

    return y


def _download_image(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        response = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert('RGBA')
    except Exception:
        return _download_image_with_curl(url)


def _download_image_with_curl(url: str) -> Image.Image | None:
    try:
        result = subprocess.run(
            [
                'curl',
                '-L',
                '--silent',
                '--show-error',
                '--max-time',
                '10',
                '--user-agent',
                'Mozilla/5.0',
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
