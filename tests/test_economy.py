"""Ekonomi sistemi testleri.

``database`` katmanı (bakiye, atomik ekleme, liderlik tablosu, cooldown)
ve ``Economy._check_cooldown`` mantığı test edilir. Discord'a bağlanmaz,
yalnızca geçici bir SQLite veritabanı kullanır.
"""

import time

import pytest

from conftest import run

# ---------------------------------------------------------------------------
# Bakiye
# ---------------------------------------------------------------------------


def test_get_balance_default_zero(db):
    assert run(db.get_balance(123, 456)) == 0


def test_set_balance(db):
    run(db.set_balance(123, 456, 500))
    assert run(db.get_balance(123, 456)) == 500


def test_add_balance_creates_row(db):
    new = run(db.add_balance(123, 456, 250))
    assert new == 250
    assert run(db.get_balance(123, 456)) == 250


def test_add_balance_accumulates(db):
    run(db.add_balance(123, 456, 100))
    run(db.add_balance(123, 456, 50))
    assert run(db.get_balance(123, 456)) == 150


def test_add_balance_atomic_upsert(db):
    """add_balance mevcut bakiyenin üzerine eklemeli, sıfırlamamalı."""
    run(db.set_balance(123, 456, 300))
    new = run(db.add_balance(123, 456, 100))
    assert new == 400
    assert run(db.get_balance(123, 456)) == 400


def test_add_balance_negative(db):
    run(db.set_balance(123, 456, 500))
    new = run(db.add_balance(123, 456, -200))
    assert new == 300


def test_balance_is_guild_scoped(db):
    run(db.add_balance(123, 456, 100))
    assert run(db.get_balance(999, 456)) == 0


# ---------------------------------------------------------------------------
# Liderlik tablosu
# ---------------------------------------------------------------------------


def test_balance_leaderboard_ordering(db):
    run(db.set_balance(123, 1, 50))
    run(db.set_balance(123, 2, 900))
    run(db.set_balance(123, 3, 250))
    rows = run(db.get_balance_leaderboard(123))
    assert [user_id for user_id, _ in rows] == [2, 3, 1]
    assert [bal for _, bal in rows] == [900, 250, 50]


def test_balance_leaderboard_limit(db):
    for uid in range(1, 6):
        run(db.set_balance(123, uid, uid * 10))
    rows = run(db.get_balance_leaderboard(123, limit=3))
    assert len(rows) == 3


def test_balance_leaderboard_empty(db):
    assert run(db.get_balance_leaderboard(123)) == []


# ---------------------------------------------------------------------------
# Cooldown (bekleme süresi)
# ---------------------------------------------------------------------------


def test_get_cooldown_default_zero(db):
    assert run(db.get_cooldown(123, 456, "daily")) == 0


def test_set_and_get_cooldown(db):
    run(db.set_cooldown(123, 456, "daily", 1_800_000_000))
    assert run(db.get_cooldown(123, 456, "daily")) == 1_800_000_000


def test_cooldown_claim_scoped(db):
    run(db.set_cooldown(123, 456, "daily", 1_800_000_000))
    assert run(db.get_cooldown(123, 456, "weekly")) == 0


def test_check_cooldown_returns_remaining(db):
    pytest.importorskip("discord")
    from cogs.economy import Economy

    cog = Economy.__new__(Economy)
    now = int(time.time())

    # Gelecekte biten bir bekleme süresi → kalan saniye dönmeli
    run(db.set_cooldown(123, 456, "daily", now + 3600))
    remaining = run(cog._check_cooldown(123, 456, "daily"))
    assert 0 < remaining <= 3600

    # Süresi dolmuş bekleme → 0 dönmeli
    run(db.set_cooldown(123, 456, "daily", now - 10))
    assert run(cog._check_cooldown(123, 456, "daily")) == 0

    # Hiç kayıt yok → 0 dönmeli
    assert run(cog._check_cooldown(123, 789, "daily")) == 0
