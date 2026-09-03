"""Seviye sistemi testleri.

``xp_for_level`` / ``level_from_xp`` matematik fonksiyonları ve
XP veritabanı katmanı test edilir.
"""

import pytest

from conftest import run

pytest.importorskip("discord")

from cogs.levels import level_from_xp, xp_for_level  # noqa: E402

# ---------------------------------------------------------------------------
# XP matematik fonksiyonları
# ---------------------------------------------------------------------------


def test_xp_for_level_known_values():

    # xp_for_level(level) = 100 * level^2
    assert xp_for_level(0) == 0
    assert xp_for_level(1) == 100
    assert xp_for_level(2) == 400
    assert xp_for_level(3) == 900
    assert xp_for_level(5) == 2500
    assert xp_for_level(10) == 10000


def test_level_from_xp_known_values():
    assert level_from_xp(0) == 0
    assert level_from_xp(99) == 0
    assert level_from_xp(100) == 1
    assert level_from_xp(399) == 1
    assert level_from_xp(400) == 2
    assert level_from_xp(2500) == 5


def test_level_from_xp_roundtrip():
    """Tam seviye eşikleri, o seviyeye denk gelen XP'ye dönmeli."""
    for level in range(0, 50):
        assert level_from_xp(xp_for_level(level)) == level


def test_level_from_xp_monotonic():
    """XP arttıkça seviye asla düşmemeli."""
    last = 0
    for xp in range(0, 100_000, 137):
        current = level_from_xp(xp)
        assert current >= last
        last = current


# ---------------------------------------------------------------------------
# XP veritabanı
# ---------------------------------------------------------------------------


def test_get_xp_default_zero(db):
    assert run(db.get_xp(123, 456)) == 0


def test_add_xp_accumulates(db):
    run(db.add_xp(123, 456, 15))
    run(db.add_xp(123, 456, 15))
    assert run(db.get_xp(123, 456)) == 30


def test_xp_is_guild_scoped(db):
    run(db.add_xp(123, 456, 100))
    assert run(db.get_xp(999, 456)) == 0


def test_level_leaderboard_ordering(db):
    run(db.add_xp(123, 1, 500))
    run(db.add_xp(123, 2, 1200))
    run(db.add_xp(123, 3, 100))
    rows = run(db.get_level_leaderboard(123))
    assert [user_id for user_id, _ in rows] == [2, 1, 3]


def test_level_leaderboard_limit(db):
    for uid in range(1, 6):
        run(db.add_xp(123, uid, uid * 100))
    rows = run(db.get_level_leaderboard(123, limit=3))
    assert len(rows) == 3


def test_level_leaderboard_empty(db):
    assert run(db.get_level_leaderboard(123)) == []


# ---------------------------------------------------------------------------
# Detay istatistikler (mesaj sayısı, ses süresi, bot logları)
# ---------------------------------------------------------------------------


def test_add_message_xp_increments_counter(db):
    run(db.add_message_xp(123, 456, 15))
    stats = run(db.get_level_stats(123, 456))
    assert stats["xp"] == 15
    assert stats["messages"] == 1
    run(db.add_message_xp(123, 456, 15))
    stats = run(db.get_level_stats(123, 456))
    assert stats["xp"] == 30
    assert stats["messages"] == 2


def test_add_voice_seconds_accumulates(db):
    run(db.add_voice_seconds(123, 456, 60))
    run(db.add_voice_seconds(123, 456, 120))
    stats = run(db.get_level_stats(123, 456))
    assert stats["voice_seconds"] == 180
    assert stats["xp"] == 0


def test_level_stats_default_zero(db):
    stats = run(db.get_level_stats(123, 456))
    assert stats == {"xp": 0, "messages": 0, "voice_seconds": 0}


def test_bot_log_count(db):
    assert run(db.get_bot_log_count(123)) == 0
    run(db.incr_bot_log_count(123))
    run(db.incr_bot_log_count(123))
    assert run(db.get_bot_log_count(123)) == 2
    assert run(db.get_bot_log_count(999)) == 0
