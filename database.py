import json
import os
import time

import aiosqlite

DB_PATH = os.path.join("data", "bot.db")


def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)


def guild_config(guild_id):
    cfg = load_config()
    base = {k: v for k, v in cfg.items() if k != "guilds"}
    overrides = cfg.get("guilds", {}).get(str(guild_id), {})
    for section, values in overrides.items():
        if isinstance(values, dict) and isinstance(base.get(section), dict):
            base[section] = {**base[section], **values}
        else:
            base[section] = values
    return base


def save_config(data):
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def get_db():
    os.makedirs("data", exist_ok=True)
    return await aiosqlite.connect(DB_PATH)


async def init_db():
    db = await get_db()
    try:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER NOT NULL,
                key      TEXT NOT NULL,
                value    TEXT NOT NULL,
                PRIMARY KEY (guild_id, key)
            );

            CREATE TABLE IF NOT EXISTS warns (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                mod_id   INTEGER NOT NULL,
                reason   TEXT NOT NULL,
                created  INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS levels (
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                xp            INTEGER NOT NULL DEFAULT 0,
                messages      INTEGER NOT NULL DEFAULT 0,
                voice_seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS invite_uses (
                guild_id   INTEGER NOT NULL,
                inviter_id INTEGER NOT NULL,
                uses       INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, inviter_id)
            );

            CREATE TABLE IF NOT EXISTS joins (
                guild_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                inviter_id INTEGER NOT NULL,
                joined_at  INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                status     TEXT NOT NULL DEFAULT 'open',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS whitelist (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS blacklist (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS protected_roles (
                guild_id INTEGER NOT NULL,
                role_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS protected_members (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS channel_snapshot (
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                data       TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS role_snapshot (
                guild_id INTEGER NOT NULL,
                role_id  INTEGER NOT NULL,
                data     TEXT NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS economy (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                balance  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS economy_cooldowns (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                claim    TEXT NOT NULL,
                expires  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id, claim)
            );

            CREATE TABLE IF NOT EXISTS afk (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                reason   TEXT NOT NULL DEFAULT 'AFK',
                since    INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                remind_at INTEGER NOT NULL,
                text     TEXT NOT NULL,
                done     INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS role_menus (
                guild_id   INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                payload    TEXT NOT NULL,
                PRIMARY KEY (guild_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS gender_verify (
                message_id INTEGER PRIMARY KEY,
                guild_id   INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS giveaways (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id  INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                end_at    INTEGER NOT NULL,
                winners   INTEGER NOT NULL DEFAULT 1,
                prize     TEXT NOT NULL,
                done      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS suggestions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id   INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                content    TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS tags (
                guild_id INTEGER NOT NULL,
                name     TEXT NOT NULL,
                content  TEXT NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS punishments (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                kind     TEXT NOT NULL,
                until    INTEGER NOT NULL,
                reason   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS automod_words (
                guild_id INTEGER NOT NULL,
                word     TEXT NOT NULL,
                PRIMARY KEY (guild_id, word)
            );

            CREATE TABLE IF NOT EXISTS manifest_roles (
                message_id INTEGER NOT NULL,
                guild_id   INTEGER NOT NULL,
                emoji_id   INTEGER NOT NULL,
                role_id    INTEGER NOT NULL,
                PRIMARY KEY (message_id, emoji_id)
            );
            """
        )
        await db.commit()

        cur = await db.execute("PRAGMA table_info(levels)")
        columns = {row[1] for row in await cur.fetchall()}
        if "messages" not in columns:
            await db.execute("ALTER TABLE levels ADD COLUMN messages INTEGER NOT NULL DEFAULT 0")
        if "voice_seconds" not in columns:
            await db.execute(
                "ALTER TABLE levels ADD COLUMN voice_seconds INTEGER NOT NULL DEFAULT 0"
            )
        await db.commit()
    finally:
        await db.close()


async def get_setting(guild_id, key, default=None):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT value FROM settings WHERE guild_id = ? AND key = ?", (guild_id, key)
        )
        row = await cur.fetchone()
        return row[0] if row else default
    finally:
        await db.close()


async def set_setting(guild_id, key, value):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO settings (guild_id, key, value) VALUES (?, ?, ?)",
            (guild_id, key, str(value)),
        )
        await db.commit()
    finally:
        await db.close()


async def add_warn(guild_id, user_id, mod_id, reason):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO warns (guild_id, user_id, mod_id, reason, created) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, mod_id, reason, int(time.time())),
        )
        await db.commit()
    finally:
        await db.close()


async def get_warns(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT mod_id, reason, created FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY created DESC",
            (guild_id, user_id),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def clear_warns(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM warns WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def add_xp(guild_id, user_id, amount):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO levels (guild_id, user_id, xp) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?",
            (guild_id, user_id, amount, amount),
        )
        await db.commit()
    finally:
        await db.close()


async def get_xp(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()


async def add_message_xp(guild_id, user_id, amount):
    """Mesaj kaynaklı XP verir ve toplam mesaj sayacını artırır."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, messages) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = xp + ?, messages = messages + 1",
            (guild_id, user_id, amount, amount),
        )
        await db.commit()
    finally:
        await db.close()


async def add_voice_seconds(guild_id, user_id, seconds):
    """Ses kanalında geçirilen süreyi kaydeder."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, voice_seconds) VALUES (?, ?, 0, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET voice_seconds = voice_seconds + ?",
            (guild_id, user_id, seconds, seconds),
        )
        await db.commit()
    finally:
        await db.close()


async def get_level_stats(guild_id, user_id):
    """XP, toplam mesaj ve toplam ses süresi verilerini döndürür."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT xp, messages, voice_seconds FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        if row is None:
            return {"xp": 0, "messages": 0, "voice_seconds": 0}
        return {"xp": row[0], "messages": row[1] or 0, "voice_seconds": row[2] or 0}
    finally:
        await db.close()


async def incr_bot_log_count(guild_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (guild_id, key, value) VALUES (?, 'bot_log_count', '1') "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value = CAST(value AS INTEGER) + 1",
            (guild_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_bot_log_count(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT value FROM settings WHERE guild_id = ? AND key = 'bot_log_count'", (guild_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        await db.close()


async def get_level_leaderboard(guild_id, limit=10):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def add_invite_use(guild_id, inviter_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO invite_uses (guild_id, inviter_id, uses) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, inviter_id) DO UPDATE SET uses = uses + 1",
            (guild_id, inviter_id),
        )
        await db.execute(
            "INSERT INTO joins (guild_id, user_id, inviter_id, joined_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, inviter_id, int(time.time())),
        )
        await db.commit()
    finally:
        await db.close()


async def get_invite_uses(guild_id, inviter_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT uses FROM invite_uses WHERE guild_id = ? AND inviter_id = ?",
            (guild_id, inviter_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()


async def get_invite_leaderboard(guild_id, limit=10):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT inviter_id, uses FROM invite_uses WHERE guild_id = ? ORDER BY uses DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def get_joiner(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT inviter_id, joined_at FROM joins WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return {"inviter_id": row[0], "joined_at": row[1]} if row else None
    finally:
        await db.close()


async def create_ticket(guild_id, channel_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, user_id, int(time.time())),
        )
        await db.commit()
    finally:
        await db.close()


async def close_ticket(guild_id, channel_id):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE tickets SET status = 'closed' WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_user_open_ticket(guild_id, user_id):
    """Kullanıcının açık bir ticket kanalı varsa channel_id döner, yoksa None."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open' "
            "ORDER BY created_at DESC LIMIT 1",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await db.close()


async def is_whitelisted(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM whitelist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return (await cur.fetchone()) is not None
    finally:
        await db.close()


async def add_whitelist(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO whitelist (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def remove_whitelist(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM whitelist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_whitelist(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id FROM whitelist WHERE guild_id = ?", (guild_id,)
        )
        return [row[0] for row in await cur.fetchall()]
    finally:
        await db.close()


async def is_blacklisted(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return (await cur.fetchone()) is not None
    finally:
        await db.close()


async def add_blacklist(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO blacklist (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def remove_blacklist(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_blacklist(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id FROM blacklist WHERE guild_id = ?", (guild_id,)
        )
        return [row[0] for row in await cur.fetchall()]
    finally:
        await db.close()


async def is_protected_role(guild_id, role_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM protected_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )
        return (await cur.fetchone()) is not None
    finally:
        await db.close()


async def add_protected_role(guild_id, role_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO protected_roles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )
        await db.commit()
    finally:
        await db.close()


async def remove_protected_role(guild_id, role_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM protected_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_protected_roles(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT role_id FROM protected_roles WHERE guild_id = ?", (guild_id,)
        )
        return [row[0] for row in await cur.fetchall()]
    finally:
        await db.close()


async def is_protected_member(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM protected_members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return (await cur.fetchone()) is not None
    finally:
        await db.close()


async def add_protected_member(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO protected_members (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def remove_protected_member(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM protected_members WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_protected_members(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id FROM protected_members WHERE guild_id = ?", (guild_id,)
        )
        return [row[0] for row in await cur.fetchall()]
    finally:
        await db.close()


async def save_channel_snapshot(guild_id, channel_id, data):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO channel_snapshot (guild_id, channel_id, data) VALUES (?, ?, ?)",
            (guild_id, channel_id, json.dumps(data, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_channel_snapshots(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT channel_id, data FROM channel_snapshot WHERE guild_id = ?", (guild_id,)
        )
        rows = await cur.fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
    finally:
        await db.close()


async def delete_channel_snapshot(guild_id, channel_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM channel_snapshot WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        await db.commit()
    finally:
        await db.close()


async def save_role_snapshot(guild_id, role_id, data):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO role_snapshot (guild_id, role_id, data) VALUES (?, ?, ?)",
            (guild_id, role_id, json.dumps(data, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_role_snapshots(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT role_id, data FROM role_snapshot WHERE guild_id = ?", (guild_id,)
        )
        rows = await cur.fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
    finally:
        await db.close()


async def delete_role_snapshot(guild_id, role_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM role_snapshot WHERE guild_id = ? AND role_id = ?", (guild_id, role_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_balance(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()


async def set_balance(guild_id, user_id, amount):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO economy (guild_id, user_id, balance) VALUES (?, ?, ?)",
            (guild_id, user_id, amount),
        )
        await db.commit()
    finally:
        await db.close()


async def add_balance(guild_id, user_id, amount):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO economy (guild_id, user_id, balance) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET balance = balance + ?",
            (guild_id, user_id, amount, amount),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row[0] if row else amount
    finally:
        await db.close()


async def get_balance_leaderboard(guild_id, limit=10):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id, balance FROM economy WHERE guild_id = ? ORDER BY balance DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def set_cooldown(guild_id, user_id, claim, expires):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO economy_cooldowns (guild_id, user_id, claim, expires) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, claim, expires),
        )
        await db.commit()
    finally:
        await db.close()


async def get_cooldown(guild_id, user_id, claim):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT expires FROM economy_cooldowns WHERE guild_id = ? AND user_id = ? AND claim = ?",
            (guild_id, user_id, claim),
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()


async def set_afk(guild_id, user_id, reason):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO afk (guild_id, user_id, reason, since) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, reason, int(time.time())),
        )
        await db.commit()
    finally:
        await db.close()


async def get_afk(guild_id, user_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT reason, since FROM afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return {"reason": row[0], "since": row[1]} if row else None
    finally:
        await db.close()


async def remove_afk(guild_id, user_id):
    db = await get_db()
    try:
        await db.execute("DELETE FROM afk WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()
    finally:
        await db.close()


async def add_reminder(guild_id, user_id, channel_id, remind_at, text):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO reminders (guild_id, user_id, channel_id, remind_at, text) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, channel_id, remind_at, text),
        )
        await db.commit()
    finally:
        await db.close()


async def get_due_reminders():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, guild_id, user_id, channel_id, text FROM reminders WHERE done = 0 AND remind_at <= ?",
            (int(time.time()),),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def mark_reminder_done(reminder_id):
    db = await get_db()
    try:
        await db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
        await db.commit()
    finally:
        await db.close()


async def save_role_menu(guild_id, message_id, channel_id, payload):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO role_menus (guild_id, message_id, channel_id, payload) VALUES (?, ?, ?, ?)",
            (guild_id, message_id, channel_id, json.dumps(payload, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_role_menus(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT message_id, channel_id, payload FROM role_menus WHERE guild_id = ?", (guild_id,)
        )
        rows = await cur.fetchall()
        return [{"message_id": r[0], "channel_id": r[1], "payload": json.loads(r[2])} for r in rows]
    finally:
        await db.close()


async def delete_role_menu(guild_id, message_id):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM role_menus WHERE guild_id = ? AND message_id = ?", (guild_id, message_id)
        )
        await db.commit()
    finally:
        await db.close()


async def save_gender_verify(guild_id, channel_id, message_id, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO gender_verify (message_id, guild_id, channel_id, user_id) VALUES (?, ?, ?, ?)",
            (message_id, guild_id, channel_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_gender_verify(message_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT message_id, guild_id, channel_id, user_id FROM gender_verify WHERE message_id = ?",
            (message_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {"message_id": row[0], "guild_id": row[1], "channel_id": row[2], "user_id": row[3]}
    finally:
        await db.close()


async def delete_gender_verify(message_id):
    db = await get_db()
    try:
        await db.execute("DELETE FROM gender_verify WHERE message_id = ?", (message_id,))
        await db.commit()
    finally:
        await db.close()


async def add_giveaway(guild_id, message_id, channel_id, end_at, winners, prize):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO giveaways (guild_id, message_id, channel_id, end_at, winners, prize) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, message_id, channel_id, end_at, winners, prize),
        )
        await db.commit()
    finally:
        await db.close()


async def get_active_giveaways(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, message_id, channel_id, end_at, winners, prize FROM giveaways WHERE guild_id = ? AND done = 0",
            (guild_id,),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def mark_giveaway_done(giveaway_id):
    db = await get_db()
    try:
        await db.execute("UPDATE giveaways SET done = 1 WHERE id = ?", (giveaway_id,))
        await db.commit()
    finally:
        await db.close()


async def add_suggestion(guild_id, message_id, channel_id, user_id, content):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO suggestions (guild_id, message_id, channel_id, user_id, content) VALUES (?, ?, ?, ?, ?)",
            (guild_id, message_id, channel_id, user_id, content),
        )
        await db.commit()
    finally:
        await db.close()


async def set_suggestion_status(message_id, status):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE suggestions SET status = ? WHERE message_id = ?", (status, message_id)
        )
        await db.commit()
    finally:
        await db.close()


async def save_tag(guild_id, name, content, user_id):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO tags (guild_id, name, content, user_id) VALUES (?, ?, ?, ?)",
            (guild_id, name.lower(), content, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_tag(guild_id, name):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT content FROM tags WHERE guild_id = ? AND name = ?", (guild_id, name.lower())
        )
        row = await cur.fetchone()
        return row[0] if row else None
    finally:
        await db.close()


async def delete_tag(guild_id, name):
    db = await get_db()
    try:
        await db.execute("DELETE FROM tags WHERE guild_id = ? AND name = ?", (guild_id, name.lower()))
        await db.commit()
    finally:
        await db.close()


async def get_tags(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT name FROM tags WHERE guild_id = ? ORDER BY name", (guild_id,)
        )
        return [r[0] for r in await cur.fetchall()]
    finally:
        await db.close()


async def add_punishment(guild_id, user_id, kind, until, reason):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO punishments (guild_id, user_id, kind, until, reason) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, kind, until, reason),
        )
        await db.commit()
    finally:
        await db.close()


async def get_active_punishments(guild_id, kind):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT user_id, until, reason FROM punishments WHERE guild_id = ? AND kind = ?",
            (guild_id, kind),
        )
        return await cur.fetchall()
    finally:
        await db.close()


async def get_user_punishment(guild_id, user_id, kind):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT until, reason FROM punishments WHERE guild_id = ? AND user_id = ? AND kind = ?",
            (guild_id, user_id, kind),
        )
        row = await cur.fetchone()
        return {"until": row[0], "reason": row[1]} if row else None
    finally:
        await db.close()


async def remove_punishment(guild_id, user_id, kind):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM punishments WHERE guild_id = ? AND user_id = ? AND kind = ?",
            (guild_id, user_id, kind),
        )
        await db.commit()
    finally:
        await db.close()


async def add_automod_word(guild_id, word):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO automod_words (guild_id, word) VALUES (?, ?)",
            (guild_id, word.lower()),
        )
        await db.commit()
    finally:
        await db.close()


async def remove_automod_word(guild_id, word):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM automod_words WHERE guild_id = ? AND word = ?", (guild_id, word.lower())
        )
        await db.commit()
    finally:
        await db.close()


async def get_automod_words(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT word FROM automod_words WHERE guild_id = ?", (guild_id,)
        )
        return [r[0] for r in await cur.fetchall()]
    finally:
        await db.close()


async def save_manifest_roles(guild_id, message_id, emoji_role_pairs):
    db = await get_db()
    try:
        for emoji_id, role_id in emoji_role_pairs:
            await db.execute(
                "INSERT OR IGNORE INTO manifest_roles (message_id, guild_id, emoji_id, role_id) VALUES (?, ?, ?, ?)",
                (message_id, guild_id, emoji_id, role_id),
            )
        await db.commit()
    finally:
        await db.close()


async def get_manifest_roles(message_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT message_id, guild_id, emoji_id, role_id FROM manifest_roles WHERE message_id = ?",
            (message_id,),
        )
        rows = await cur.fetchall()
        return [
            {"message_id": r[0], "guild_id": r[1], "emoji_id": r[2], "role_id": r[3]}
            for r in rows
        ]
    finally:
        await db.close()


async def get_guild_manifest_roles(guild_id):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT message_id, guild_id, emoji_id, role_id FROM manifest_roles WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [
            {"message_id": r[0], "guild_id": r[1], "emoji_id": r[2], "role_id": r[3]}
            for r in rows
        ]
    finally:
        await db.close()
