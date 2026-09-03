import io
import math
import os
import random

from PIL import Image, ImageDraw, ImageFont

from utils.fonts import load_font

WIDTH, HEIGHT = 800, 400
SS = 2

_PALETTES = [
    [(11, 16, 38), (59, 30, 92), (139, 47, 102)],
    [(16, 24, 46), (40, 48, 120), (90, 60, 140)],
    [(20, 14, 46), (70, 26, 100), (150, 60, 90)],
    [(8, 14, 34), (30, 46, 110), (88, 120, 200)],
    [(26, 12, 40), (84, 30, 90), (170, 70, 110)],
]

_SPECIAL_FONTS = {
    "javanese": [
        "C:/Windows/Fonts/javatext.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifJavanese-Regular.ttf",
    ],
    "tibetan": [
        "C:/Windows/Fonts/himalaya.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansTibetan-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    ],
}

_WATERMARK = "꧁༺Impackt༻꧂"

_GLOW_CACHE = {}
_PALETTE_CACHE = {}


def _font(size, bold=True):
    return load_font(size, bold=bold)


def _special_font(size, kind):
    for path in _SPECIAL_FONTS.get(kind, []):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def _char_font(char, size):
    cp = ord(char)
    if cp in (0xA9C1, 0xA9C2):
        return _special_font(size, "javanese") or _font(size, bold=False)
    if cp in (0x0F3A, 0x0F3B):
        return _special_font(size, "tibetan") or _font(size, bold=False)
    return _font(size)


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _palette(t):
    t = max(0.0, min(t, 1.0))
    seg = t * (len(_PALETTES) - 1)
    i = min(int(seg), len(_PALETTES) - 2)
    f = seg - i
    return [_lerp_color(_PALETTES[i][k], _PALETTES[i + 1][k], f) for k in range(3)]


def _gradient(size, colors):
    w, h = size
    key = (w, h) + tuple(c for col in colors for c in col)
    cached = _PALETTE_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    grad = Image.new("RGB", (1, len(colors)))
    for i, c in enumerate(colors):
        grad.putpixel((0, i), c)
    out = grad.resize((1, h), Image.BILINEAR).resize((w, h))
    _PALETTE_CACHE[key] = out
    return out.copy()


def _rounded_box(draw, box, radius, fill, outline=None, width=0):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _text(draw, xy, text, font, fill=(255, 255, 255, 255), shadow=True, anchor="mm"):
    x, y = xy
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, 170), anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _fit_text(font, text, max_width):
    while font.getlength(text) > max_width and len(text) > 1:
        text = text[:-1]
    return text + "..." if font.getlength(text) < font.getlength(text + "…") else text


def _circle_avatar(avatar, size, ring_color=(255, 255, 255)):
    avatar = avatar.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(avatar, (0, 0), mask)
    ring = Image.new("RGBA", (size + 20, size + 20), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, size + 20, size + 20), outline=ring_color + (160,), width=6)
    ring.paste(out, (10, 10), out)
    return ring


def _radial_glow(size, color=(90, 190, 255), max_alpha=110):
    key = (size, color, max_alpha)
    cached = _GLOW_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    cx = cy = size / 2
    steps = 26
    for i in range(steps, 0, -1):
        r = (size / 2) * i / steps
        a = int(max_alpha * (steps - i) / steps)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (a,))
    _GLOW_CACHE[key] = glow
    return glow.copy()


def _dashed_ring(size, offset):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = size // 2 - 14
    cx = cy = size / 2
    dash, gap = 14, 18
    total = dash + gap
    i = 0
    while i < 360:
        d.arc((cx - r, cy - r, cx + r, cy + r), start=offset + i, end=offset + i + dash, fill=(180, 240, 255, 200), width=5)
        i += total
    return layer


def _mixed_text_image(text, size, color=(255, 255, 255), alpha=255):
    fonts = [_char_font(c, size) for c in text]
    widths = [int(f.getlength(c)) for c, f in zip(text, fonts)]
    total = sum(widths)
    pad = int(size * 0.3)
    img = Image.new("RGBA", (total + pad * 2, int(size * 1.6)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = pad
    for c, f, cw in zip(text, fonts, widths):
        d.text((x, int(size * 1.25)), c, font=f, fill=color + (alpha,), anchor="ls")
        x += cw
    return img


def _watermark(img, text, size, y, color=(255, 255, 255), alpha=26):
    wm = _mixed_text_image(text, size, color=color, alpha=alpha)
    x = (img.width - wm.width) // 2
    img.alpha_composite(wm, (x, y - wm.height // 2))


def _render_frame(avatar, title, name, subtitle, progress, t, total, watermark=_WATERMARK):
    w, h = WIDTH * SS, HEIGHT * SS
    colors = _palette(t / total)
    img = _gradient((w, h), colors).convert("RGBA")

    phase = t / total * math.tau

    bg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    db = ImageDraw.Draw(bg)

    # Arka plan ışık huzmeleri
    rng = random.Random(2026)
    for _ in range(14):
        bx = rng.uniform(0, w)
        by = rng.uniform(0, h)
        length = rng.uniform(140, 320) * SS
        ang = rng.uniform(-math.pi / 4, math.pi / 4)
        alpha = rng.randint(8, 22)
        x1 = bx + math.cos(ang) * length
        y1 = by + math.sin(ang) * length
        db.line((bx, by, x1, y1), fill=(255, 255, 255, alpha), width=rng.randint(1, 3) * SS)

    # Gezinen ışık topları (eşmerkezli, blur taklidi)
    orbs = [
        (w * 0.16, h * 0.22, 150, (120, 180, 255)),
        (w * 0.84, h * 0.70, 190, (255, 120, 200)),
        (w * 0.78, h * 0.18, 100, (180, 120, 255)),
    ]
    for i, (ox, oy, r, oc) in enumerate(orbs):
        ox = (ox + 30 * SS * math.sin(phase + i * 2.1)) % w
        oy = oy + 20 * SS * math.sin(phase + i * 1.7)
        for k in range(10, 0, -1):
            rr = r * k / 10
            a = int(28 * (11 - k) / 11)
            db.ellipse((ox - rr, oy - rr, ox + rr, oy + rr), fill=oc + (a,))
    img.alpha_composite(bg)

    # Üst / alt karartma (derinlik)
    fade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    df = ImageDraw.Draw(fade)
    for i in range(46):
        a = int(60 * (1 - i / 46))
        df.line((0, i, w, i), fill=(0, 0, 0, a))
    for i in range(56):
        a = int(50 * (1 - i / 56))
        df.line((0, h - i, w, h - i), fill=(0, 0, 0, a))
    img.alpha_composite(fade)

    # Arka plan filigranı: ꧁༺Impackt༻꧂
    _watermark(img, watermark, 58 * SS, int(h * 0.50), alpha=22)
    _watermark(img, watermark, 26 * SS, int(h * 0.94), alpha=16)

    # Parçacıklar
    part = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dp = ImageDraw.Draw(part)
    prng = random.Random(1234)
    for p in range(30):
        bx = prng.uniform(0, w)
        by = prng.uniform(0, h)
        speed = prng.uniform(20, 90) * SS
        radius = prng.uniform(1.2, 3.6) * SS
        x = (bx + speed * t) % w
        y = by + math.sin(phase + p * 1.3) * 12 * SS
        alpha = int(60 + 130 * (0.5 + 0.5 * math.sin(phase + p * 0.9)))
        dp.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, alpha))
    img.alpha_composite(part)

    # Kart çerçevesi (parlayan ince kenarlık)
    frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dfr = ImageDraw.Draw(frame)
    glow_w = int(10 * SS + 8 * SS * (0.5 + 0.5 * math.sin(phase * 2)))
    _rounded_box(dfr, (0, 0, w, h), 24 * SS, None, (255, 255, 255, 26), width=glow_w)
    _rounded_box(dfr, (int(6 * SS), int(6 * SS), w - 6 * SS, h - 6 * SS), 20 * SS, None, (255, 255, 255, 60), width=3)
    img.alpha_composite(frame)

    # Avatar + parıltı + dönen kesikli halka
    av_size = 150 * SS
    avatar_img = _circle_avatar(avatar, av_size)
    ax = (w - av_size) // 2 - 10 * SS
    ay = 46 * SS
    glow = _radial_glow(av_size + 120 * SS, color=(90, 190, 255))
    img.alpha_composite(glow, (ax - 60 * SS, ay - 60 * SS))
    ring = _dashed_ring(av_size + 56 * SS, int(phase * 180 / math.pi))
    img.alpha_composite(ring, (ax - 28 * SS, ay - 28 * SS))
    img.alpha_composite(avatar_img, (ax, ay))

    # Metinler
    title_font = _font(46 * SS, bold=True)
    name_font = _font(40 * SS, bold=True)
    sub_font = _font(24 * SS, bold=False)

    _text(d := ImageDraw.Draw(img, "RGBA"), (w // 2, 30 * SS), title, title_font)
    display_name = _fit_text(name_font, name, w - 120 * SS)
    _text(d, (w // 2, int(av_size + 108 * SS)), display_name, name_font)
    _text(d, (w // 2, int(av_size + 160 * SS)), subtitle, sub_font, fill=(235, 240, 255, 235))

    # İlerleme çubuğu
    bar_w = int(w * 0.56)
    bar_h = 18 * SS
    bx = (w - bar_w) // 2
    by = h - 52 * SS
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dbar = ImageDraw.Draw(bar)
    _rounded_box(dbar, (bx, by, bx + bar_w, by + bar_h), bar_h // 2, (0, 0, 0, 150))
    fill_w = int(bar_w * progress)
    if fill_w > 0:
        grad_cols = [((80, 200, 255), (120, 140, 255)), ((120, 140, 255), (255, 120, 200))]
        c1, c2 = grad_cols[t % len(grad_cols)]
        segs = 12
        for s in range(segs):
            x0 = bx + int(fill_w * s / segs)
            x1 = bx + int(fill_w * (s + 1) / segs)
            fc = _lerp_color(c1, c2, s / segs) + (255,)
            _rounded_box(dbar, (x0, by, x1, by + bar_h), bar_h // 2, fc)
        hl_w = int(bar_w * 0.16)
        hl_x = bx + int(fill_w * (0.5 + 0.5 * math.sin(phase * 2))) if fill_w > hl_w else bx
        _rounded_box(dbar, (hl_x, by, min(hl_x + hl_w, bx + fill_w), by + bar_h), bar_h // 2, (255, 255, 255, 180))
    img.alpha_composite(bar)

    # Parlama (shine) süpürmesi
    shine_w = 110 * SS
    sx = (t / total) * (w + shine_w * 2) - shine_w
    shine = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shine).rectangle((sx, 0, sx + shine_w, h), fill=(255, 255, 255, 26))
    shine = shine.rotate(16, resample=Image.BICUBIC)
    img = Image.alpha_composite(img, shine)

    return img.convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)


def _make_gif(frames, duration=90):
    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        optimize=True,
    )
    buf.seek(0)
    return buf.getvalue()


def _avatar_from_bytes(data, size):
    try:
        return Image.open(io.BytesIO(data)).resize((size, size), Image.LANCZOS)
    except Exception:
        fallback = Image.new("RGB", (size, size), (88, 101, 242))
        d = ImageDraw.Draw(fallback)
        d.ellipse((0, 0, size, size), fill=(114, 137, 218))
        return fallback


def create_welcome_gif(avatar_data, name, member_count, frames=22):
    avatar = _avatar_from_bytes(avatar_data, 150)
    total = len(range(frames))
    rendered = []
    for t in range(frames):
        rendered.append(
            _render_frame(
                avatar,
                "HOŞ GELDİN",
                name,
                f"Üye sayısı: {member_count}",
                1.0,
                t,
                total,
            )
        )
    return _make_gif(rendered)


def create_level_gif(avatar_data, name, level, current_xp, needed_xp, frames=26):
    avatar = _avatar_from_bytes(avatar_data, 150)
    progress = 1.0 if needed_xp <= 0 else max(0.0, min(current_xp / needed_xp, 1.0))
    rendered = []
    for t in range(frames):
        fill = progress * (t + 1) / frames
        rendered.append(
            _render_frame(
                avatar,
                "SEVİYE ATLADIN!",
                name,
                f"Seviye {level}  •  {current_xp}/{needed_xp} XP",
                fill,
                t,
                frames,
            )
        )
    return _make_gif(rendered)
