from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BG = '#1E2330'
TEAL = '#00C9B1'
YELLOW = '#FFE14D'
SURFACE = '#0D0F14'
MUTED = '#8892A4'
WHITE = '#F6F8FB'
SOFT = '#151923'

FONT_DIR = Path('/usr/share/fonts/truetype/liberation')
REGULAR = FONT_DIR / 'LiberationSans-Regular.ttf'
BOLD = FONT_DIR / 'LiberationSans-Bold.ttf'


class Canvas:
    def __init__(self, size: tuple[int, int], scale: int = 3) -> None:
        self.size = size
        self.scale = scale
        self.image = Image.new('RGB', (size[0] * scale, size[1] * scale), BG)
        self.draw = ImageDraw.Draw(self.image)

    def s(self, value: int | float) -> int:
        return round(value * self.scale)

    def box(self, xy: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(self.s(v) for v in xy)

    def font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(BOLD if bold else REGULAR), self.s(size))

    def text(
        self,
        xy: tuple[int, int],
        value: str,
        size: int,
        fill: str = WHITE,
        bold: bool = False,
        anchor: str | None = None,
    ) -> None:
        self.draw.text(
            (self.s(xy[0]), self.s(xy[1])),
            value,
            font=self.font(size, bold),
            fill=fill,
            anchor=anchor,
        )

    def text_size(self, value: str, size: int, bold: bool = False) -> tuple[int, int]:
        bbox = self.draw.textbbox((0, 0), value, font=self.font(size, bold))
        return ((bbox[2] - bbox[0]) // self.scale, (bbox[3] - bbox[1]) // self.scale)

    def rounded(
        self,
        xy: tuple[int, int, int, int],
        radius: int,
        fill: str,
        outline: str | None = None,
        width: int = 1,
    ) -> None:
        self.draw.rounded_rectangle(
            self.box(xy),
            radius=self.s(radius),
            fill=fill,
            outline=outline,
            width=self.s(width),
        )

    def line(self, xy: tuple[int, int, int, int], fill: str, width: int = 1) -> None:
        self.draw.line(self.box(xy), fill=fill, width=self.s(width))

    def ellipse(self, xy: tuple[int, int, int, int], fill: str) -> None:
        self.draw.ellipse(self.box(xy), fill=fill)

    def polygon(self, points: list[tuple[int, int]], fill: str) -> None:
        self.draw.polygon([(self.s(x), self.s(y)) for x, y in points], fill=fill)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        final = self.image.resize(self.size, Image.Resampling.LANCZOS)
        final.save(path, 'PNG', optimize=True)


def draw_logo(c: Canvas, x: int, y: int, size: int) -> None:
    c.rounded((x, y, x + size, y + size), 14, TEAL)
    c.ellipse((x + 13, y + 14, x + size - 13, y + size - 18), SURFACE)
    c.line((x + 24, y + 30, x + size - 24, y + 30), TEAL, 4)
    c.ellipse((x + 23, y + 28, x + 31, y + 36), TEAL)
    c.ellipse((x + size - 31, y + 28, x + size - 23, y + 36), TEAL)


def draw_badge(c: Canvas, x: int, y: int, text: str, fill: str = YELLOW) -> None:
    tw, th = c.text_size(text, 24, True)
    c.rounded((x, y, x + tw + 42, y + 48), 24, fill)
    c.text((x + 21, y + 12), text, 24, SURFACE, True)


def draw_check(c: Canvas, x: int, y: int, label: str, size: int = 28) -> None:
    c.rounded((x, y + 2, x + 30, y + 32), 15, TEAL)
    c.line((x + 8, y + 17, x + 14, y + 23), SURFACE, 4)
    c.line((x + 14, y + 23, x + 24, y + 10), SURFACE, 4)
    c.text((x + 46, y), label, size, WHITE, False)


def instagram_story(path: Path) -> None:
    c = Canvas((1080, 1920))

    c.ellipse((760, -120, 1210, 330), '#243044')
    c.ellipse((-180, 1260, 290, 1730), '#172B35')
    c.ellipse((735, 1350, 1110, 1725), '#2A2A20')

    draw_logo(c, 88, 92, 74)
    c.text((182, 105), 'descontos.bot', 39, TEAL, True)
    draw_badge(c, 850, 106, 'NOVO')

    c.text((88, 310), 'SHOPEE', 118, WHITE, True)
    c.text((88, 434), 'CHEGOU', 136, TEAL, True)
    c.text((92, 600), 'Ofertas com link de afiliado', 43, MUTED)

    c.rounded((88, 735, 992, 1014), 42, SURFACE, TEAL, 3)
    c.text((138, 776), '81% OFF', 132, YELLOW, True)
    c.text((144, 926), 'garimpado, organizado e publicado nos canais', 32, MUTED)

    cards = [
        ('+100', 'ofertas'),
        ('Categorias', 'para encontrar rápido'),
        ('Automático', 'publicação contínua'),
    ]
    y = 1100
    for index, (title, subtitle) in enumerate(cards):
        x = 88 + index * 308
        c.rounded((x, y, x + 276, y + 250), 28, SOFT, '#293245', 2)
        c.ellipse((x + 28, y + 28, x + 82, y + 82), TEAL if index != 1 else YELLOW)
        if index == 0:
            c.text((x + 104, y + 45), title, 42, WHITE, True)
        else:
            c.text((x + 28, y + 112), title, 33, WHITE, True)
        if index == 0:
            c.text((x + 32, y + 128), subtitle, 31, MUTED)
        else:
            c.text((x + 28, y + 160), subtitle, 25, MUTED)

    c.rounded((88, 1436, 992, 1606), 34, '#111720')
    c.text((132, 1477), '@descontos.bot — WhatsApp e Telegram', 37, WHITE, True)
    c.text((132, 1538), '#publicidade', 31, MUTED)

    c.line((88, 1750, 992, 1750), '#333B4C', 2)
    c.text((540, 1810), 'links de afiliado Shopee nos canais', 30, MUTED, False, 'mm')

    c.save(path)


def whatsapp_image(path: Path) -> None:
    c = Canvas((800, 680))

    c.ellipse((610, -110, 920, 200), '#243044')
    c.ellipse((-110, 430, 190, 730), '#172B35')

    draw_logo(c, 48, 40, 52)
    c.text((116, 50), 'descontos.bot', 31, TEAL, True)
    draw_badge(c, 642, 48, 'NOVO')

    c.text((48, 133), 'Shopee CHEGOU!', 58, WHITE, True)
    c.text((50, 200), 'Ofertas com link de afiliado nos canais', 27, MUTED)

    # Offer card with correct data
    c.rounded((48, 260, 752, 450), 26, SURFACE, '#293245', 2)
    c.text((84, 280), 'Saysosayso Brincalhão Tubarão Carteira', 24, WHITE, True)
    c.text((84, 312), 'Miniatura Bolsa Moedas Fone Ouvido...', 24, WHITE, True)
    c.text((84, 360), 'R$ 25,32', 52, YELLOW, True)
    c.text((310, 376), 'De R$ 42,92', 27, MUTED)
    # Strikethrough on original price
    c.rounded((590, 340, 720, 400), 28, YELLOW)
    c.text((655, 370), '41% OFF', 25, SURFACE, True, 'mm')

    draw_check(c, 60, 478, 'Shopee integrada', 25)
    draw_check(c, 60, 524, 'Publicação automática', 25)
    draw_check(c, 60, 570, 'WhatsApp e Telegram', 25)

    c.rounded((382, 490, 752, 600), 22, '#111720')
    c.text((410, 516), 'Os links da Shopee já estão', 24, WHITE, True)
    c.text((410, 550), 'sendo publicados no grupo!', 24, WHITE, True)

    c.text((752, 645), '#publicidade', 22, MUTED, False, 'ra')

    c.save(path)


def main() -> None:
    target = Path('/mnt/c/Users/marce/OneDrive/Desktop')
    try:
        instagram_story(target / 'shopee-story-instagram.png')
        whatsapp_image(target / 'shopee-whatsapp.png')
    except OSError as error:
        print(f'Desktop unavailable: {error}')
        target = Path('generated/social')
        instagram_story(target / 'shopee-story-instagram.png')
        whatsapp_image(target / 'shopee-whatsapp.png')

    print(target / 'shopee-story-instagram.png')
    print(target / 'shopee-whatsapp.png')


if __name__ == '__main__':
    main()
