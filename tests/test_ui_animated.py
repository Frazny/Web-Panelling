"""Animasyonlu emoji değiştirme testleri.

``ui.animated`` ve ``ui.apply_animated`` fonksiyonlarının statik emojileri,
sunucuda varsa animasyonlu karşılıklarıyla değiştirdiği doğrulanır.
"""

import pytest

pytest.importorskip("discord")

import discord  # noqa: E402

from utils import emoji_anim, ui  # noqa: E402


class _Emo:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return f"<a:{self.name}:1234567890>"


class _Guild:
    def __init__(self, emojis):
        self.emojis = emojis


ALL_EMOJIS = [_Emo(name) for name in {p["name"] for p in emoji_anim.PACK}]
GUILD = _Guild(ALL_EMOJIS)
EMPTY_GUILD = _Guild([])


def test_all_mapped_names_exist_in_pack():
    pack_names = {p["name"] for p in emoji_anim.PACK}
    for name in ui.ANIM_EMOJI.values():
        assert name in pack_names


def test_animated_replaces_known_emoji():
    result = ui.animated("✅ Başarılı", GUILD)
    assert "<a:anim_onay:1234567890>" in result
    assert "✅" not in result


def test_animated_keeps_unknown_emoji():
    result = ui.animated("🎲 Bilinmeyen", GUILD)
    assert "🎲" in result


def test_animated_no_guild_returns_unchanged():
    assert ui.animated("✅ Test", None) == "✅ Test"


def test_animated_handles_variation_selector():
    assert ui.animated("🛡", GUILD) == "<a:anim_kalkan:1234567890>"
    assert ui.animated("🛡️", GUILD) == "<a:anim_kalkan:1234567890>"


def test_animated_skips_when_emoji_missing():
    assert ui.animated("✅ Test", EMPTY_GUILD) == "✅ Test"


def test_apply_animated_transforms_embed():
    e = discord.Embed(
        title="✅ Başarılı",
        description="⚠️ Dikkat",
        color=0x2ECC71,
    )
    e.add_field(name="Durum", value="❌ Hata")
    ui.apply_animated(e, GUILD)
    assert "<a:anim_onay:1234567890>" in e.title
    assert "<a:anim_uyari:1234567890>" in e.description
    assert e.fields[0].name == "Durum"
    assert "<a:anim_red:1234567890>" in e.fields[0].value


def test_apply_animated_none_safe():
    assert ui.apply_animated(None, GUILD) is None
