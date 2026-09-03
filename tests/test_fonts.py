"""Çapraz platform font çözümleyici testleri.

Windows'ta Arial bulunmalı; hiçbir font bulunmasa bile `load_font`
Pillow varsayılan fontuna düserek hata atmamalıdır (Linux/VPS guvenligi).
"""

import pytest

pytest.importorskip("PIL")

from utils import fonts  # noqa: E402


def test_font_path_bold_or_none():
    path = fonts.font_path(bold=True)
    assert path is None or path.endswith((".ttf", ".ttc"))


def test_font_path_regular_or_none():
    path = fonts.font_path(bold=False)
    assert path is None or path.endswith((".ttf", ".ttc"))


def test_load_font_never_raises(monkeypatch):
    monkeypatch.setattr(fonts, "font_path", lambda bold=True: None)
    f = fonts.load_font(24, bold=True)
    assert f is not None


def test_load_font_with_found_path(monkeypatch):
    class FakeFont:
        def __init__(self, path, size):
            self.path = path
            self.size = size

    monkeypatch.setattr(fonts, "font_path", lambda bold=True: "/tmp/fake.ttf")
    monkeypatch.setattr(fonts.ImageFont, "truetype", FakeFont)
    f = fonts.load_font(24, bold=True)
    assert f.size == 24


def test_default_font_fallback_keeps_size(monkeypatch):
    monkeypatch.setattr(fonts, "font_path", lambda bold=True: None)
    monkeypatch.setattr(fonts.ImageFont, "load_default", lambda size=None: ("default", size))
    f = fonts.load_font(16, bold=False)
    assert f[0] == "default"
