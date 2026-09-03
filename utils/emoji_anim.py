"""Sunucuya yüklenecek animasyonlu (GIF) emoji paketini üretir.

Emoji karakterleri Pillow ile renkli render edilemediği için tüm
çizimler vektörel ilkellerle (elips, poligon, çizgi) sıfırdan yapılır.
Her emoji, bir çizim fonksiyonu ve bir hareket (effect) kombinasyonudur.
"""

import io
import math

from PIL import Image, ImageDraw

from utils.fonts import load_font

SIZE = 256
FRAMES = 24
FPS = 24
SS = 3

TAU = math.tau

# ---------------------------------------------------------------------------
# Renk paleti
# ---------------------------------------------------------------------------

RED = (231, 76, 60)
GREEN = (46, 204, 113)
AMBER = (241, 196, 15)
GOLD = (241, 196, 15)
GOLD_DARK = (212, 172, 13)
GOLD_LIGHT = (253, 235, 130)
PURPLE = (155, 89, 182)
CYAN = (52, 152, 219)
CYAN_LIGHT = (133, 193, 233)
GRAY = (127, 140, 141)
GRAY_DARK = (85, 92, 95)
WHITE = (255, 255, 255)
DARK = (44, 42, 40)
BLOOD = (192, 57, 43)


def _font(size):
    return load_font(size, bold=True)


# ---------------------------------------------------------------------------
# Hareket (effect) transformları
# ---------------------------------------------------------------------------


def _pulse(t, size):
    return 1 + 0.10 * math.sin(TAU * t), 0.0, 0, 0, 255


def _spin(t, size):
    return 1.0, 360.0 * t, 0, 0, 255


def _bounce(t, size):
    return 1.0, 0.0, 0, int(size * 0.12 * abs(math.sin(TAU * t))), 255


def _shake(t, size):
    return 1.0, 0.0, int(size * 0.06 * math.sin(2 * TAU * t)), 0, 255


def _blink(t, size):
    alpha = int(255 - 115 * (1 - math.cos(TAU * t)) / 2)
    return 1.0, 0.0, 0, 0, alpha


def _float_(t, size):
    return 1.0, 0.0, 0, -int(size * 0.05 * (1 + math.sin(TAU * t)) / 2), 255


def _glow_pulse(t, size):
    return 1 + 0.04 * math.sin(TAU * t), 0.0, 0, 0, 255


def _none(t, size):
    return 1.0, 0.0, 0, 0, 255


_EFFECTS = {
    "none": _none,
    "pulse": _pulse,
    "spin": _spin,
    "bounce": _bounce,
    "shake": _shake,
    "blink": _blink,
    "float": _float_,
    "glow": _glow_pulse,
}


def _transform(image, scale, angle, dx, dy, alpha):
    w = h = image.size[0]
    s = max(0.1, scale)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    im = image.resize((nw, nh), Image.LANCZOS)
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = (w - im.width) // 2 + dx
    y = (h - im.height) // 2 + dy
    canvas.paste(im, (x, y), im)
    if alpha < 255:
        r, g, b, a = canvas.split()
        canvas = Image.merge("RGBA", (r, g, b, a.point(lambda v: v * alpha // 255)))
    return canvas


# ---------------------------------------------------------------------------
# Çizim yardımcıları
# ---------------------------------------------------------------------------


def _star4(cx, cy, r1, r2, rot=0.0):
    pts = []
    for k in range(8):
        a = math.radians(45 * k) + rot
        r = r1 if k % 2 == 0 else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _star5(cx, cy, r1, r2, rot=-math.pi / 2):
    pts = []
    for k in range(10):
        a = rot + math.radians(36 * k)
        r = r1 if k % 2 == 0 else r2
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _glow(d, cx, cy, r, color, max_alpha=70, layers=3):
    for i in range(layers):
        a = int(max_alpha / (i + 1))
        rr = r * (1.0 + 0.13 * i)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))


# ---------------------------------------------------------------------------
# Emoji çizimleri (d, canvas boyutu s, zaman t, kare indeksi i, toplam kare)
# ---------------------------------------------------------------------------


def draw_heart(d, s, t, i, frames):
    color = (230, 60, 80)
    cx, cy = 0.5 * s, 0.40 * s
    r = 0.21 * s
    _glow(d, cx, cy + 0.05 * s, r + 0.05 * s, color)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    d.ellipse([cx + 0.13 * s - r, cy - r, cx + 0.13 * s + r, cy + r], fill=color)
    d.polygon(
        [(cx - r - 0.13 * s, cy + 0.01 * s), (cx + r + 0.13 * s, cy + 0.01 * s), (cx + 0.065 * s, cy + 0.52 * s)],
        fill=color,
    )
    shine = (255, 170, 190, 200)
    d.ellipse([cx - 0.09 * s, cy - 0.10 * s, cx - 0.02 * s, cy - 0.03 * s], fill=shine)


def draw_sparkle(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    d.polygon(_star4(cx, cy, 0.44 * s, 0.15 * s), fill=GOLD)
    d.polygon(_star4(cx, cy, 0.30 * s, 0.09 * s), fill=GOLD_LIGHT)
    d.polygon(_star4(0.16 * s, 0.20 * s, 0.11 * s, 0.04 * s), fill=GOLD)
    d.polygon(_star4(0.84 * s, 0.78 * s, 0.08 * s, 0.03 * s), fill=GOLD_LIGHT)


def draw_check(d, s, t, i, frames):
    pts = [(0.20 * s, 0.56 * s), (0.42 * s, 0.76 * s), (0.82 * s, 0.26 * s)]
    d.line(pts, fill=WHITE, width=int(0.16 * s), joint="curve")
    d.line(pts, fill=GREEN, width=int(0.10 * s), joint="curve")
    p = (1 - math.cos(TAU * t)) / 2
    if p < 0.5:
        f = p * 2
        x = pts[0][0] + (pts[1][0] - pts[0][0]) * f
        y = pts[0][1] + (pts[1][1] - pts[0][1]) * f
    else:
        f = (p - 0.5) * 2
        x = pts[1][0] + (pts[2][0] - pts[1][0]) * f
        y = pts[1][1] + (pts[2][1] - pts[1][1]) * f
    r = 0.07 * s
    d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)


def draw_cross(d, s, t, i, frames):
    c = 0.5 * s
    half = 0.36 * s
    w = int(0.16 * s)
    d.line([(c - half, c - half), (c + half, c + half)], fill=WHITE, width=w + int(0.03 * s))
    d.line([(c + half, c - half), (c - half, c + half)], fill=WHITE, width=w + int(0.03 * s))
    d.line([(c - half, c - half), (c + half, c + half)], fill=RED, width=w)
    d.line([(c + half, c - half), (c - half, c + half)], fill=RED, width=w)


def draw_warn(d, s, t, i, frames):
    d.polygon([(0.5 * s, 0.12 * s), (0.07 * s, 0.90 * s), (0.93 * s, 0.90 * s)], fill=AMBER)
    d.polygon(
        [(0.5 * s, 0.12 * s), (0.07 * s, 0.90 * s), (0.93 * s, 0.90 * s)],
        outline=DARK,
        width=int(0.02 * s),
    )
    on = math.sin(TAU * 2 * t) > 0
    if on:
        bar = int(0.10 * s)
        d.rounded_rectangle(
            [0.45 * s, 0.32 * s, 0.55 * s, 0.62 * s],
            radius=bar // 2,
            fill=DARK,
        )
        d.ellipse([0.44 * s, 0.72 * s, 0.56 * s, 0.84 * s], fill=DARK)


def draw_shield(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    pts = [(0.5 * s, 0.06 * s), (0.87 * s, 0.18 * s), (0.87 * s, 0.47 * s), (0.5 * s, 0.95 * s), (0.13 * s, 0.47 * s), (0.13 * s, 0.18 * s)]
    _glow(d, cx, cy, 0.40 * s, BLOOD, max_alpha=55)
    d.polygon(pts, fill=BLOOD)
    d.polygon(pts, outline=WHITE, width=int(0.02 * s))
    shine = (255, 160, 150, 90)
    d.polygon([(0.24 * s, 0.24 * s), (0.42 * s, 0.24 * s), (0.32 * s, 0.78 * s)], fill=shine)


def draw_coin(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    r = 0.38 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD_DARK, width=int(0.04 * s))
    rr = 0.30 * s
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=GOLD_DARK, width=int(0.02 * s))
    fnt = _font(int(0.42 * s))
    d.text((cx, cy + 0.02 * s), "$", font=fnt, fill=DARK, anchor="mm")
    a = TAU * t
    gx = cx + r * 0.55 * math.cos(a)
    gy = cy + r * 0.55 * math.sin(a)
    gr = 0.08 * s
    d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=(255, 255, 255, 220))


def draw_gem(d, s, t, i, frames):
    pts = [(0.5 * s, 0.05 * s), (0.91 * s, 0.42 * s), (0.5 * s, 0.95 * s), (0.09 * s, 0.42 * s)]
    d.polygon(pts, fill=CYAN)
    d.polygon(pts, outline=CYAN_LIGHT, width=int(0.02 * s))
    d.line([(0.5 * s, 0.05 * s), (0.5 * s, 0.95 * s)], fill=CYAN_LIGHT, width=int(0.015 * s))
    d.line([(0.09 * s, 0.42 * s), (0.91 * s, 0.42 * s)], fill=CYAN_LIGHT, width=int(0.015 * s))
    d.polygon([(0.26 * s, 0.42 * s), (0.74 * s, 0.42 * s), (0.5 * s, 0.95 * s)], fill=(30, 100, 160))
    shine = (220, 245, 255, 200)
    d.ellipse([0.28 * s, 0.14 * s, 0.42 * s, 0.28 * s], fill=shine)
    d.polygon(_star4(0.20 * s, 0.20 * s, 0.09 * s, 0.03 * s), fill=WHITE)


def draw_note(d, s, t, i, frames):
    color = PURPLE
    hx, hy = 0.44 * s, 0.72 * s
    r = 0.09 * s
    d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=color)
    d.ellipse([hx + 0.14 * s - r, hy - r, hx + 0.14 * s + r, hy + r], fill=color)
    for ex in (hx + 0.01 * s, hx + 0.15 * s):
        d.line([(ex + 0.02 * s, hy - 0.03 * s), (ex + 0.02 * s, 0.16 * s)], fill=color, width=int(0.035 * s))
    d.polygon([(0.62 * s, 0.16 * s), (0.62 * s, 0.30 * s), (0.72 * s, 0.24 * s)], fill=color)


def draw_trophy(d, s, t, i, frames):
    cx = 0.5 * s
    _glow(d, cx, 0.5 * s, 0.36 * s, GOLD, max_alpha=50)
    d.polygon([(0.28 * s, 0.16 * s), (0.72 * s, 0.16 * s), (0.68 * s, 0.60 * s), (0.32 * s, 0.60 * s)], fill=GOLD)
    d.rounded_rectangle([0.26 * s, 0.10 * s, 0.74 * s, 0.22 * s], radius=0.04 * s, fill=GOLD)
    d.rectangle([0.46 * s, 0.60 * s, 0.54 * s, 0.74 * s], fill=GOLD_DARK)
    d.ellipse([0.30 * s, 0.70 * s, 0.70 * s, 0.86 * s], fill=GOLD)
    w = int(0.045 * s)
    d.arc([0.22 * s, 0.30 * s, 0.32 * s, 0.52 * s], 90, 270, fill=GOLD, width=w)
    d.arc([0.68 * s, 0.30 * s, 0.78 * s, 0.52 * s], -90, 90, fill=GOLD, width=w)
    d.line([(0.46 * s, 0.18 * s), (0.46 * s, 0.55 * s)], fill=GOLD_LIGHT, width=int(0.02 * s))
    d.polygon(_star4(0.16 * s, 0.16 * s, 0.08 * s, 0.03 * s), fill=GOLD_LIGHT)


def draw_lock(d, s, t, i, frames):
    color = GOLD
    d.arc([0.32 * s, 0.05 * s, 0.68 * s, 0.50 * s], 180, 360, fill=color, width=int(0.08 * s))
    d.rounded_rectangle(
        [0.20 * s, 0.38 * s, 0.80 * s, 0.92 * s],
        radius=0.08 * s,
        fill=GRAY,
        outline=GRAY_DARK,
        width=int(0.02 * s),
    )
    d.ellipse([0.43 * s, 0.52 * s, 0.57 * s, 0.66 * s], fill=GRAY_DARK)
    d.rounded_rectangle([0.47 * s, 0.62 * s, 0.53 * s, 0.80 * s], radius=0.02 * s, fill=GRAY_DARK)


def draw_unlock(d, s, t, i, frames):
    color = GOLD
    d.arc([0.32 * s, 0.05 * s, 0.68 * s, 0.50 * s], 160, 340, fill=color, width=int(0.08 * s))
    d.rounded_rectangle(
        [0.20 * s, 0.38 * s, 0.80 * s, 0.92 * s],
        radius=0.08 * s,
        fill=GRAY,
        outline=GRAY_DARK,
        width=int(0.02 * s),
    )
    d.ellipse([0.43 * s, 0.52 * s, 0.57 * s, 0.66 * s], fill=GRAY_DARK)
    d.rounded_rectangle([0.47 * s, 0.62 * s, 0.53 * s, 0.80 * s], radius=0.02 * s, fill=GRAY_DARK)


def draw_star5(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    _glow(d, cx, cy, 0.40 * s, GOLD, max_alpha=50)
    d.polygon(_star5(cx, cy, 0.42 * s, 0.18 * s), fill=GOLD)
    d.polygon(_star5(cx, cy, 0.42 * s, 0.18 * s), outline=GOLD_DARK, width=int(0.015 * s))
    d.polygon(_star5(cx, cy, 0.30 * s, 0.12 * s), fill=GOLD_LIGHT)


def draw_cop(d, s, t, i, frames):
    d.rounded_rectangle([0.28 * s, 0.22 * s, 0.72 * s, 0.34 * s], radius=0.04 * s, fill=GRAY_DARK)
    d.rounded_rectangle([0.20 * s, 0.28 * s, 0.80 * s, 0.31 * s], radius=0.02 * s, fill=GRAY_DARK)
    d.polygon([(0.30 * s, 0.34 * s), (0.36 * s, 0.90 * s), (0.64 * s, 0.90 * s), (0.70 * s, 0.34 * s)], fill=GRAY)
    d.rectangle([0.33 * s, 0.40 * s, 0.67 * s, 0.78 * s], fill=GRAY_DARK)
    d.rectangle([0.35 * s, 0.45 * s, 0.44 * s, 0.75 * s], fill=GRAY)
    d.rectangle([0.56 * s, 0.45 * s, 0.65 * s, 0.75 * s], fill=GRAY)
    d.rounded_rectangle([0.30 * s, 0.30 * s, 0.70 * s, 0.34 * s], radius=0.02 * s, fill=(140, 148, 150))


def draw_parti(d, s, t, i, frames):
    d.polygon([(0.5 * s, 0.30 * s), (0.14 * s, 0.88 * s), (0.86 * s, 0.88 * s)], fill=(255, 120, 160))
    d.polygon([(0.5 * s, 0.30 * s), (0.14 * s, 0.88 * s), (0.86 * s, 0.88 * s)], outline=WHITE, width=int(0.02 * s))
    d.polygon([(0.5 * s, 0.30 * s), (0.24 * s, 0.46 * s), (0.5 * s, 0.62 * s)], fill=(255, 200, 120))
    colors = [(255, 120, 160), GOLD, CYAN, GREEN]
    for k, (dx, dy) in enumerate(
        [(-0.30, -0.18), (0.30, -0.22), (0.12, -0.34), (-0.05, -0.40), (0.40, -0.06), (-0.42, -0.02)]
    ):
        d.ellipse(
            [(0.5 + dx) * s - 0.05 * s, (0.5 + dy) * s - 0.05 * s, (0.5 + dx) * s + 0.05 * s, (0.5 + dy) * s + 0.05 * s],
            fill=colors[k % len(colors)],
        )


def draw_liste(d, s, t, i, frames):
    d.rounded_rectangle([0.22 * s, 0.10 * s, 0.78 * s, 0.90 * s], radius=0.05 * s, fill=(190, 195, 200))
    d.rounded_rectangle([0.28 * s, 0.16 * s, 0.72 * s, 0.84 * s], radius=0.03 * s, fill=WHITE)
    d.rounded_rectangle([0.38 * s, 0.10 * s, 0.62 * s, 0.20 * s], radius=0.03 * s, fill=GRAY_DARK)
    d.rectangle([0.40 * s, 0.06 * s, 0.60 * s, 0.12 * s], fill=GRAY)
    for yy in (0.28, 0.40, 0.52, 0.64):
        d.line([(0.34 * s, yy * s), (0.66 * s, yy * s)], fill=(205, 210, 220), width=int(0.03 * s))
    d.line([(0.34 * s, 0.76 * s), (0.56 * s, 0.76 * s)], fill=CYAN, width=int(0.035 * s))


def draw_indir(d, s, t, i, frames):
    d.rounded_rectangle([0.18 * s, 0.20 * s, 0.82 * s, 0.86 * s], radius=0.06 * s, fill=GRAY)
    d.rounded_rectangle([0.18 * s, 0.20 * s, 0.82 * s, 0.86 * s], radius=0.06 * s, outline=GRAY_DARK, width=int(0.02 * s))
    d.polygon([(0.22 * s, 0.26 * s), (0.78 * s, 0.26 * s), (0.70 * s, 0.40 * s), (0.30 * s, 0.40 * s)], fill=GRAY_DARK)
    d.polygon([(0.5 * s, 0.44 * s), (0.36 * s, 0.62 * s), (0.64 * s, 0.62 * s)], fill=GREEN)
    d.rectangle([0.46 * s, 0.30 * s, 0.54 * s, 0.52 * s], fill=GREEN)
    d.rectangle([0.30 * s, 0.74 * s, 0.70 * s, 0.82 * s], fill=GRAY_DARK)


def draw_davet(d, s, t, i, frames):
    d.rectangle([0.18 * s, 0.24 * s, 0.82 * s, 0.78 * s], fill=(230, 235, 240), outline=(150, 155, 165), width=int(0.02 * s))
    d.polygon([(0.18 * s, 0.24 * s), (0.5 * s, 0.48 * s), (0.82 * s, 0.24 * s)], fill=(175, 185, 195))
    d.line([(0.18 * s, 0.78 * s), (0.42 * s, 0.50 * s)], fill=(150, 155, 165), width=int(0.03 * s))
    d.line([(0.82 * s, 0.78 * s), (0.58 * s, 0.50 * s)], fill=(150, 155, 165), width=int(0.03 * s))


def draw_ban(d, s, t, i, frames):
    d.rounded_rectangle([0.30 * s, 0.14 * s, 0.70 * s, 0.42 * s], radius=0.05 * s, fill=GRAY)
    d.rounded_rectangle([0.30 * s, 0.14 * s, 0.70 * s, 0.42 * s], radius=0.05 * s, outline=GRAY_DARK, width=int(0.02 * s))
    d.rectangle([0.34 * s, 0.14 * s, 0.66 * s, 0.18 * s], fill=GRAY_DARK)
    d.rectangle([0.46 * s, 0.42 * s, 0.54 * s, 0.88 * s], fill=(150, 100, 60))
    d.rounded_rectangle([0.44 * s, 0.84 * s, 0.56 * s, 0.92 * s], radius=0.02 * s, fill=(120, 80, 45))
    d.rectangle([0.48 * s, 0.22 * s, 0.52 * s, 0.34 * s], fill=(215, 220, 225))


def draw_yasak(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    r = 0.40 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(160, 40, 35), width=int(0.02 * s))
    d.line([(cx - 0.26 * s, cy + 0.26 * s), (cx + 0.26 * s, cy - 0.26 * s)], fill=WHITE, width=int(0.10 * s))


def draw_hediye(d, s, t, i, frames):
    d.polygon([(0.20 * s, 0.42 * s), (0.80 * s, 0.42 * s), (0.72 * s, 0.30 * s), (0.28 * s, 0.30 * s)], fill=(230, 90, 130))
    d.rounded_rectangle([0.20 * s, 0.42 * s, 0.80 * s, 0.90 * s], radius=0.04 * s, fill=(255, 120, 160))
    d.rectangle([0.44 * s, 0.30 * s, 0.56 * s, 0.90 * s], fill=(255, 200, 60))
    d.rectangle([0.28 * s, 0.36 * s, 0.72 * s, 0.42 * s], fill=(255, 200, 60))
    d.polygon([(0.5 * s, 0.30 * s), (0.40 * s, 0.10 * s), (0.56 * s, 0.10 * s)], fill=(255, 200, 60))


def draw_bilet(d, s, t, i, frames):
    d.rounded_rectangle([0.14 * s, 0.26 * s, 0.86 * s, 0.74 * s], radius=0.05 * s, fill=PURPLE)
    d.rounded_rectangle([0.14 * s, 0.26 * s, 0.86 * s, 0.74 * s], radius=0.05 * s, outline=(105, 55, 125), width=int(0.02 * s))
    d.ellipse([0.25 * s, 0.42 * s, 0.35 * s, 0.58 * s], fill=(105, 55, 125))
    d.ellipse([0.65 * s, 0.42 * s, 0.75 * s, 0.58 * s], fill=(105, 55, 125))
    d.line([(0.40 * s, 0.34 * s), (0.40 * s, 0.66 * s)], fill=WHITE, width=int(0.02 * s))
    d.rounded_rectangle([0.46 * s, 0.38 * s, 0.62 * s, 0.45 * s], radius=0.02 * s, fill=WHITE)
    d.rounded_rectangle([0.46 * s, 0.52 * s, 0.58 * s, 0.57 * s], radius=0.015 * s, fill=WHITE)


def draw_tekme(d, s, t, i, frames):
    d.polygon(
        [(0.30 * s, 0.30 * s), (0.70 * s, 0.30 * s), (0.78 * s, 0.70 * s), (0.64 * s, 0.86 * s), (0.36 * s, 0.86 * s), (0.22 * s, 0.70 * s)],
        fill=(150, 100, 60),
    )
    d.polygon([(0.30 * s, 0.30 * s), (0.70 * s, 0.30 * s), (0.72 * s, 0.40 * s), (0.28 * s, 0.40 * s)], fill=(120, 80, 45))
    d.rectangle([0.42 * s, 0.46 * s, 0.58 * s, 0.80 * s], fill=(120, 80, 45))
    for yy in (0.50, 0.58, 0.66):
        d.line([(0.44 * s, yy * s), (0.56 * s, yy * s)], fill=WHITE, width=int(0.018 * s))


def draw_sus(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    r = 0.40 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 210, 110))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(205, 165, 65), width=int(0.02 * s))
    d.ellipse([cx - 0.20 * s, cy - 0.20 * s, cx - 0.10 * s, cy - 0.10 * s], fill=DARK)
    d.ellipse([cx + 0.10 * s, cy - 0.20 * s, cx + 0.20 * s, cy - 0.10 * s], fill=DARK)
    d.line([(cx - 0.24 * s, cy + 0.10 * s), (cx + 0.24 * s, cy + 0.10 * s)], fill=GRAY_DARK, width=int(0.04 * s))
    d.rectangle([cx - 0.03 * s, cy + 0.02 * s, cx + 0.03 * s, cy + 0.26 * s], fill=GRAY_DARK)


def draw_grafik(d, s, t, i, frames):
    bars = [(0.22, 0.60, GREEN), (0.40, 0.42, CYAN), (0.58, 0.28, GOLD), (0.72, 0.52, RED)]
    for x, top, col in bars:
        d.rounded_rectangle([x * s, top * s, (x + 0.11) * s, 0.86 * s], radius=0.03 * s, fill=col)
    d.line([(0.20 * s, 0.66 * s), (0.48 * s, 0.34 * s), (0.82 * s, 0.24 * s)], fill=DARK, width=int(0.04 * s))
    d.ellipse([0.50 * s, 0.16 * s, 0.56 * s, 0.22 * s], fill=WHITE)


def draw_ses(d, s, t, i, frames):
    d.polygon(
        [(0.28 * s, 0.32 * s), (0.44 * s, 0.32 * s), (0.60 * s, 0.20 * s), (0.60 * s, 0.80 * s), (0.44 * s, 0.68 * s), (0.28 * s, 0.68 * s)],
        fill=GRAY,
    )
    d.polygon([(0.60 * s, 0.38 * s), (0.72 * s, 0.48 * s), (0.72 * s, 0.68 * s), (0.60 * s, 0.78 * s)], fill=GRAY)
    for rr in (0.10, 0.18, 0.26):
        x0 = 0.72 * s - rr * s
        y0 = 0.5 * s - rr * s
        d.arc([x0, y0, x0 + 2 * rr * s, y0 + 2 * rr * s], -60, 60, fill=GRAY, width=int(0.035 * s))


def draw_melodi(d, s, t, i, frames):
    for k, (nx, ny) in enumerate([(0.26, 0.62), (0.52, 0.42), (0.76, 0.72)]):
        r = 0.06 * s
        d.ellipse([nx * s - r, ny * s - r, nx * s + r, ny * s + r], fill=PURPLE)
        d.line([(nx * s + r, ny * s), (nx * s + r, (ny - 0.46) * s)], fill=PURPLE, width=int(0.028 * s))
        d.polygon(
            [(nx * s + r, (ny - 0.46) * s), (nx * s + r, (ny - 0.34) * s), (nx * s + r + 0.12 * s, (ny - 0.40) * s)],
            fill=PURPLE,
        )


def draw_altin(d, s, t, i, frames):
    d.polygon(
        [(0.5 * s, 0.05 * s), (0.66 * s, 0.20 * s), (0.66 * s, 0.40 * s), (0.5 * s, 0.56 * s), (0.34 * s, 0.40 * s), (0.34 * s, 0.20 * s)],
        fill=GOLD,
    )
    d.polygon(
        [(0.5 * s, 0.05 * s), (0.66 * s, 0.20 * s), (0.66 * s, 0.40 * s), (0.5 * s, 0.56 * s), (0.34 * s, 0.40 * s), (0.34 * s, 0.20 * s)],
        outline=GOLD_DARK,
        width=int(0.015 * s),
    )
    cx, cy = 0.5 * s, 0.70 * s
    r = 0.20 * s
    _glow(d, cx, cy, r, GOLD, max_alpha=55)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD_DARK, width=int(0.02 * s))
    d.ellipse([cx - 0.09 * s, cy - 0.09 * s, cx + 0.09 * s, cy + 0.09 * s], outline=GOLD_DARK, width=int(0.02 * s))


def draw_kayit(d, s, t, i, frames):
    d.rounded_rectangle([0.22 * s, 0.14 * s, 0.78 * s, 0.86 * s], radius=0.04 * s, fill=WHITE)
    d.rounded_rectangle([0.22 * s, 0.14 * s, 0.78 * s, 0.86 * s], radius=0.04 * s, outline=(180, 185, 195), width=int(0.015 * s))
    for yy in (0.26, 0.38, 0.50, 0.62):
        d.line([(0.30 * s, yy * s), (0.70 * s, yy * s)], fill=(210, 215, 225), width=int(0.025 * s))
    d.line([(0.30 * s, 0.74 * s), (0.56 * s, 0.74 * s)], fill=(210, 215, 225), width=int(0.025 * s))
    d.polygon([(0.60 * s, 0.20 * s), (0.78 * s, 0.36 * s), (0.70 * s, 0.44 * s), (0.52 * s, 0.28 * s)], fill=(255, 200, 60))
    d.polygon([(0.78 * s, 0.36 * s), (0.82 * s, 0.40 * s), (0.72 * s, 0.43 * s), (0.70 * s, 0.44 * s)], fill=(70, 50, 30))


def draw_hedef(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    rings = [(RED, 0.40), (WHITE, 0.32), (RED, 0.24), (WHITE, 0.16), (RED, 0.07)]
    for col, rr in rings:
        d.ellipse([cx - rr * s, cy - rr * s, cx + rr * s, cy + rr * s], fill=col)
    d.ellipse([cx - 0.40 * s, cy - 0.40 * s, cx + 0.40 * s, cy + 0.40 * s], outline=(150, 150, 160), width=int(0.015 * s))


def draw_mikrofon(d, s, t, i, frames):
    cx = 0.5 * s
    d.rounded_rectangle([cx - 0.14 * s, 0.14 * s, cx + 0.14 * s, 0.54 * s], radius=0.14 * s, fill=GRAY)
    d.rounded_rectangle([cx - 0.14 * s, 0.14 * s, cx + 0.14 * s, 0.54 * s], radius=0.14 * s, outline=GRAY_DARK, width=int(0.015 * s))
    for yy in (0.28, 0.35, 0.42):
        d.line([(cx - 0.09 * s, yy * s), (cx + 0.09 * s, yy * s)], fill=GRAY_DARK, width=int(0.015 * s))
    d.rectangle([cx - 0.05 * s, 0.54 * s, cx + 0.05 * s, 0.78 * s], fill=GRAY_DARK)
    d.arc([cx - 0.22 * s, 0.58 * s, cx + 0.22 * s, 1.02 * s], 0, 180, fill=GRAY, width=int(0.03 * s))
    d.rectangle([cx - 0.24 * s, 0.84 * s, cx + 0.24 * s, 0.92 * s], fill=GRAY)


def draw_duyuru(d, s, t, i, frames):
    d.polygon([(0.20 * s, 0.28 * s), (0.72 * s, 0.20 * s), (0.72 * s, 0.56 * s), (0.20 * s, 0.64 * s)], fill=(255, 150, 60))
    d.polygon([(0.72 * s, 0.20 * s), (0.72 * s, 0.56 * s), (0.82 * s, 0.48 * s), (0.82 * s, 0.28 * s)], fill=(220, 120, 40))
    d.rectangle([0.14 * s, 0.32 * s, 0.20 * s, 0.60 * s], fill=GRAY_DARK)
    d.polygon([(0.20 * s, 0.46 * s), (0.30 * s, 0.60 * s), (0.20 * s, 0.64 * s)], fill=(60, 50, 40))
    for k in range(3):
        x = 0.88 * s + 0.02 * k * s
        d.line([(x, 0.30 * s), (x, 0.50 * s)], fill=(255, 150, 60), width=int(0.03 * s))


def draw_robot(d, s, t, i, frames):
    cx = 0.5 * s
    d.line([(cx, 0.24 * s), (cx, 0.10 * s)], fill=GRAY, width=int(0.03 * s))
    d.ellipse([cx - 0.04 * s, 0.04 * s, cx + 0.04 * s, 0.12 * s], fill=(255, 80, 80))
    d.rounded_rectangle([0.22 * s, 0.24 * s, 0.78 * s, 0.78 * s], radius=0.06 * s, fill=GRAY)
    d.rounded_rectangle([0.22 * s, 0.24 * s, 0.78 * s, 0.78 * s], radius=0.06 * s, outline=GRAY_DARK, width=int(0.02 * s))
    d.rectangle([0.14 * s, 0.34 * s, 0.22 * s, 0.56 * s], fill=GRAY)
    d.rectangle([0.78 * s, 0.34 * s, 0.86 * s, 0.56 * s], fill=GRAY)
    d.rounded_rectangle([0.32 * s, 0.36 * s, 0.44 * s, 0.48 * s], radius=0.02 * s, fill=(120, 220, 255))
    d.rounded_rectangle([0.56 * s, 0.36 * s, 0.68 * s, 0.48 * s], radius=0.02 * s, fill=(120, 220, 255))
    d.rounded_rectangle([0.40 * s, 0.58 * s, 0.60 * s, 0.66 * s], radius=0.02 * s, fill=GRAY_DARK)
    d.line([(0.26 * s, 0.58 * s), (0.74 * s, 0.58 * s)], fill=GRAY_DARK, width=int(0.015 * s))
    d.line([(0.26 * s, 0.66 * s), (0.74 * s, 0.66 * s)], fill=GRAY_DARK, width=int(0.015 * s))


def draw_yesil(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    r = 0.40 * s
    _glow(d, cx, cy, r, GREEN, max_alpha=55)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(30, 150, 80), width=int(0.02 * s))
    d.ellipse([cx - 0.22 * s, cy - 0.22 * s, cx - 0.10 * s, cy - 0.10 * s], fill=(160, 240, 190, 200))


def draw_kirmizi(d, s, t, i, frames):
    cx, cy = 0.5 * s, 0.5 * s
    r = 0.40 * s
    _glow(d, cx, cy, r, RED, max_alpha=55)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(160, 40, 35), width=int(0.02 * s))
    d.ellipse([cx - 0.22 * s, cy - 0.22 * s, cx - 0.10 * s, cy - 0.10 * s], fill=(250, 170, 170, 200))


def draw_ucan(d, s, t, i, frames):
    d.rounded_rectangle([0.30 * s, 0.40 * s, 0.70 * s, 0.78 * s], radius=0.03 * s, fill=(120, 200, 120))
    d.rounded_rectangle([0.30 * s, 0.40 * s, 0.70 * s, 0.78 * s], radius=0.03 * s, outline=(70, 150, 70), width=int(0.015 * s))
    d.ellipse([0.43 * s, 0.50 * s, 0.57 * s, 0.68 * s], outline=(70, 150, 70), width=int(0.02 * s))
    d.polygon([(0.30 * s, 0.40 * s), (0.10 * s, 0.20 * s), (0.26 * s, 0.12 * s), (0.36 * s, 0.28 * s)], fill=(230, 235, 240))
    d.polygon([(0.70 * s, 0.40 * s), (0.90 * s, 0.18 * s), (0.76 * s, 0.10 * s), (0.66 * s, 0.26 * s)], fill=(230, 235, 240))


def draw_kumar(d, s, t, i, frames):
    d.rounded_rectangle([0.20 * s, 0.22 * s, 0.80 * s, 0.80 * s], radius=0.05 * s, fill=(60, 70, 90))
    d.rounded_rectangle([0.20 * s, 0.22 * s, 0.80 * s, 0.80 * s], radius=0.05 * s, outline=(40, 50, 70), width=int(0.02 * s))
    fruits = [RED, GOLD, GREEN, CYAN]
    for k, x in enumerate([0.30, 0.50, 0.70]):
        col = fruits[(k + int(t * 4)) % len(fruits)]
        d.rounded_rectangle([x * s - 0.07 * s, 0.28 * s, x * s + 0.07 * s, 0.74 * s], radius=0.02 * s, fill=col)
    d.line([(0.20 * s, 0.50 * s), (0.80 * s, 0.50 * s)], fill=(40, 50, 70), width=int(0.02 * s))
    d.rectangle([0.40 * s, 0.14 * s, 0.60 * s, 0.22 * s], fill=GOLD)


# ---------------------------------------------------------------------------
# GIF üretimi
# ---------------------------------------------------------------------------


def _apply_effect(image, effect, t, size):
    scale, angle, dx, dy, alpha = _EFFECTS[effect](t, size)
    return _transform(image, scale, angle, dx, dy, alpha)


def _save_gif(frames, fps):
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),
        loop=0,
        disposal=2,
        optimize=False,
        transparency=0,
        background=0,
    )
    return buf.getvalue()


def render_gif(draw, effect="none", size=SIZE, frames=FRAMES, fps=FPS):
    """Tek bir emojiyi GIF baytları olarak üretir."""
    big = size * SS
    out = []
    for i in range(frames):
        t = i / frames
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        draw(d, big, t, i, frames)
        img = img.resize((size, size), Image.LANCZOS)
        out.append(_apply_effect(img, effect, t, size))
    return _save_gif(out, fps)


PACK = [
    {"name": "anim_kalp", "effect": "pulse", "draw": draw_heart},
    {"name": "anim_isik", "effect": "spin", "draw": draw_sparkle},
    {"name": "anim_onay", "effect": "none", "draw": draw_check},
    {"name": "anim_red", "effect": "shake", "draw": draw_cross},
    {"name": "anim_uyari", "effect": "none", "draw": draw_warn},
    {"name": "anim_kalkan", "effect": "glow", "draw": draw_shield},
    {"name": "anim_para", "effect": "pulse", "draw": draw_coin},
    {"name": "anim_elmas", "effect": "float", "draw": draw_gem},
    {"name": "anim_muzik", "effect": "bounce", "draw": draw_note},
    {"name": "anim_kupa", "effect": "glow", "draw": draw_trophy},
    {"name": "anim_kilit", "effect": "pulse", "draw": draw_lock},
    {"name": "anim_kilit_acik", "effect": "pulse", "draw": draw_unlock},
    {"name": "anim_yildiz", "effect": "spin", "draw": draw_star5},
    {"name": "anim_cop", "effect": "shake", "draw": draw_cop},
    {"name": "anim_parti", "effect": "bounce", "draw": draw_parti},
    {"name": "anim_liste", "effect": "float", "draw": draw_liste},
    {"name": "anim_indir", "effect": "bounce", "draw": draw_indir},
    {"name": "anim_davet", "effect": "float", "draw": draw_davet},
    {"name": "anim_ban", "effect": "shake", "draw": draw_ban},
    {"name": "anim_yasak", "effect": "shake", "draw": draw_yasak},
    {"name": "anim_hediye", "effect": "bounce", "draw": draw_hediye},
    {"name": "anim_bilet", "effect": "float", "draw": draw_bilet},
    {"name": "anim_tekme", "effect": "shake", "draw": draw_tekme},
    {"name": "anim_sus", "effect": "blink", "draw": draw_sus},
    {"name": "anim_grafik", "effect": "pulse", "draw": draw_grafik},
    {"name": "anim_ses", "effect": "pulse", "draw": draw_ses},
    {"name": "anim_melodi", "effect": "bounce", "draw": draw_melodi},
    {"name": "anim_altin", "effect": "glow", "draw": draw_altin},
    {"name": "anim_kayit", "effect": "pulse", "draw": draw_kayit},
    {"name": "anim_hedef", "effect": "pulse", "draw": draw_hedef},
    {"name": "anim_mikrofon", "effect": "bounce", "draw": draw_mikrofon},
    {"name": "anim_duyuru", "effect": "shake", "draw": draw_duyuru},
    {"name": "anim_robot", "effect": "pulse", "draw": draw_robot},
    {"name": "anim_yesil", "effect": "pulse", "draw": draw_yesil},
    {"name": "anim_kirmizi", "effect": "pulse", "draw": draw_kirmizi},
    {"name": "anim_ucan", "effect": "float", "draw": draw_ucan},
    {"name": "anim_kumar", "effect": "spin", "draw": draw_kumar},
]


def build_pack(size=SIZE, frames=FRAMES, fps=FPS):
    """Tüm paketi üretir: ``[{"name": str, "data": bytes}, ...]``."""
    return [
        {"name": spec["name"], "data": render_gif(spec["draw"], spec["effect"], size, frames, fps)}
        for spec in PACK
    ]
