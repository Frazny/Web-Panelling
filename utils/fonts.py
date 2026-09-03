"""Çapraz platform TTF font cözümleyici.

Windows (C:/Windows/Fonts) yanında Linux/macOS sistem font dizinlerini de
tarar. Hiçbiri bulunamazsa ``None`` döner ve çağıran Pillow'un varsayılan
fontuna düşer. Böylece bot hem PC'de hem sunucuda (Linux) çalışabilir.
"""

import os

from PIL import ImageFont

_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]

_REGULAR_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]


def font_path(bold=True):
    candidates = _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_font(size, bold=True):
    path = font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()
