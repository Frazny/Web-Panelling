"""Animasyonlu emoji paketi testleri.

``emoji_anim`` modülü üretilen GIF'lerin geçerli, animasyonlu ve
şeffaflık içermesi doğrulanır.
"""

import io
import re

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from utils import emoji_anim  # noqa: E402

NAME_RE = re.compile(r"^[a-zA-Z0-9_]{2,32}$")


def _unique_frame_count(data):
    im = Image.open(io.BytesIO(data))
    hashes = set()
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        hashes.add(im.convert("RGBA").tobytes())
    return len(hashes)


def test_pack_nonempty():
    pack = emoji_anim.build_pack()
    assert len(pack) >= 30


def test_each_gif_has_distinct_frames():
    """Her GIF en az iki farklı kare içermeli (tek kare = statik emoji)."""
    for item in emoji_anim.build_pack():
        assert _unique_frame_count(item["data"]) >= 2, item["name"]


def test_pack_names_valid():
    for item in emoji_anim.build_pack():
        assert NAME_RE.match(item["name"]), item["name"]


def test_pack_names_unique():
    names = [i["name"] for i in emoji_anim.build_pack()]
    assert len(names) == len(set(names))


def test_each_gif_is_valid_animated():
    for item in emoji_anim.build_pack():
        im = Image.open(io.BytesIO(item["data"]))
        assert im.format == "GIF"
        assert getattr(im, "n_frames", 1) > 1, item["name"]


def test_each_gif_has_transparency():
    for item in emoji_anim.build_pack():
        im = Image.open(io.BytesIO(item["data"]))
        im.seek(0)
        assert "transparency" in im.info, item["name"]
        assert im.getpixel((0, 0)) == im.info["transparency"], item["name"]


def test_each_gif_under_discord_limit():
    for item in emoji_anim.build_pack():
        assert len(item["data"]) <= 256 * 1024, item["name"]


def test_small_size_render():
    """Küçük boyutlarda da sorunsuz üretilmeli (önizleme kullanımı)."""
    data = emoji_anim.render_gif(emoji_anim.draw_check, "none", size=64, frames=8)
    assert len(data) > 0
