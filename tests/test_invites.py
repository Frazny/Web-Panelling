"""Davet sistemi testleri.

Davet kullanım sayacı ve davet liderlik tablosu test edilir.
"""

from conftest import run

# ---------------------------------------------------------------------------
# Davet kullanımı
# ---------------------------------------------------------------------------


def test_get_invite_uses_default_zero(db):
    assert run(db.get_invite_uses(123, 456)) == 0


def test_add_invite_use_increments(db):
    run(db.add_invite_use(123, 456, user_id=1001))
    assert run(db.get_invite_uses(123, 456)) == 1


def test_add_invite_use_multiple_times(db):
    for new_user in (1001, 1002, 1003):
        run(db.add_invite_use(123, 456, user_id=new_user))
    assert run(db.get_invite_uses(123, 456)) == 3


def test_invite_uses_guild_scoped(db):
    run(db.add_invite_use(123, 456, user_id=1001))
    assert run(db.get_invite_uses(999, 456)) == 0


def test_add_invite_use_records_join(db):
    """Her davet kullanımı joins tablosuna da kaydedilmeli."""
    run(db.add_invite_use(123, 456, user_id=1001))
    joins = run(_fetch_all_joins(db, 123))
    assert len(joins) == 1
    user_id, inviter_id = joins[0]
    assert user_id == 1001
    assert inviter_id == 456


# ---------------------------------------------------------------------------
# Davet liderlik tablosu
# ---------------------------------------------------------------------------


def test_invite_leaderboard_ordering(db):
    run(db.add_invite_use(123, 1, user_id=1001))
    run(db.add_invite_use(123, 2, user_id=1002))
    run(db.add_invite_use(123, 2, user_id=1003))
    rows = run(db.get_invite_leaderboard(123))
    assert [inviter_id for inviter_id, _ in rows] == [2, 1]
    assert [uses for _, uses in rows] == [2, 1]


def test_invite_leaderboard_limit(db):
    for inviter in range(1, 6):
        run(db.add_invite_use(123, inviter, user_id=1000 + inviter))
    rows = run(db.get_invite_leaderboard(123, limit=3))
    assert len(rows) == 3


def test_invite_leaderboard_empty(db):
    assert run(db.get_invite_leaderboard(123)) == []


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


async def _fetch_all_joins(db, guild_id):
    conn = await db.get_db()
    try:
        cur = await conn.execute(
            "SELECT user_id, inviter_id FROM joins WHERE guild_id = ?", (guild_id,)
        )
        return await cur.fetchall()
    finally:
        await conn.close()
