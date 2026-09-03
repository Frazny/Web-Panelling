"""Guard anti-nuke geri yükleme mantığı testleri.

Discord'a bağlanmaz; ``Guard`` cog'unun saf mantığını sahte
guild/kanal/rol nesneleriyle test eder:

- ``_restore_channels`` / ``_restore_roles``: snapshot'tan eksik kanal/rol
  geri yükleme (mevcut olanları atlama),
- ``_serialize_overwrite``: overwrite serileştirme,
- ``_snapshot_delete_is_trusted``: silme kararında whitelist/bot/audit log
  davranışı,
- ``_track_nuke``: eşik aşılınca lockdown tetiklenmesi.
"""

import discord
import pytest

from conftest import run
import database
from cogs.guard import Guard, _serialize_overwrite

# Guard, whitelist kontrolünde config.json'daki owner_id'ye bakar; testlerin
# config.json'a bağımlı olmaması için load_config'i boş döndürüyoruz.
@pytest.fixture(autouse=True)
def _no_config(monkeypatch):
    monkeypatch.setattr("utils.checks.load_config", lambda: {})


# ---------------------------------------------------------------------------
# Sahte nesneler
# ---------------------------------------------------------------------------


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeBot:
    def __init__(self, uid=999):
        self.user = FakeUser(uid)


class FakeRole:
    def __init__(
        self, rid, name="rol", position=1, color=0, permissions=0,
        hoist=False, mentionable=False, managed=False, default=False,
    ):
        self.id = rid
        self.name = name
        self.position = position
        self.color = discord.Color(color)
        self.permissions = discord.Permissions(permissions)
        self.hoist = hoist
        self.mentionable = mentionable
        self.managed = managed
        self._default = default

    def is_default(self):
        return self._default

    async def edit(self, **kw):
        return self


class FakeChannel:
    def __init__(
        self, cid, name, ctype, category_id=None, position=0,
        topic=None, nsfw=False, slowmode_delay=0, overwrites=None,
    ):
        self.id = cid
        self.name = name
        self.type = ctype
        self.category_id = category_id
        self.position = position
        self.topic = topic
        self.nsfw = nsfw
        self.slowmode_delay = slowmode_delay
        self.overwrites = overwrites or {}


class FakeGuild:
    def __init__(self, channels=None, roles=None):
        self.id = 42
        self._channels = list(channels or [])
        self._roles = list(roles or [])
        self.created_channels = []
        self.created_roles = []

    @property
    def channels(self):
        return self._channels

    @property
    def roles(self):
        return self._roles

    def get_channel(self, cid):
        return next((c for c in self._channels if c.id == cid), None)

    def get_role(self, rid):
        return next((r for r in self._roles if r.id == rid), None)

    def get_member(self, uid):
        return None

    async def create_text_channel(self, name, **kw):
        ch = FakeChannel(1000 + len(self.created_channels), name, discord.ChannelType.text)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_voice_channel(self, name, **kw):
        ch = FakeChannel(2000 + len(self.created_channels), name, discord.ChannelType.voice)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_category(self, name, **kw):
        ch = FakeChannel(3000 + len(self.created_channels), name, discord.ChannelType.category)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_role(self, name, **kw):
        role = FakeRole(9000 + len(self.created_roles), name)
        self.created_roles.append(role)
        self._roles.append(role)
        return role


class FakeAuditEntry:
    def __init__(self, user):
        self.user = user
        self.target = None


class _AsyncIter:
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class FakeGuildWithAudit(FakeGuild):
    def __init__(self, entries=None, **kw):
        super().__init__(**kw)
        self._entries = entries or []

    def audit_logs(self, **kw):
        return _AsyncIter(self._entries)


def _cog(uid=999):
    return Guard(FakeBot(uid))


def _snap_channel(cid, name, ctype, **kw):
    data = {
        "name": name,
        "type": ctype.value,
        "position": 0,
        "topic": None,
        "nsfw": False,
        "slowmode_delay": 0,
        "overwrites": [],
        "category_id": None,
    }
    data.update(kw)
    return data


# ---------------------------------------------------------------------------
# Geri yükleme
# ---------------------------------------------------------------------------


def test_restore_channels_skips_existing_restores_missing():
    guild = FakeGuild()
    existing = FakeChannel(1, "varolan", discord.ChannelType.text)
    guild._channels.append(existing)

    snapshots = {
        1: _snap_channel(1, "varolan", discord.ChannelType.text),
        2: _snap_channel(2, "yenikanal", discord.ChannelType.text, topic="konu", nsfw=True, slowmode_delay=5),
        3: _snap_channel(3, "ses", discord.ChannelType.voice),
        4: _snap_channel(4, "kategori", discord.ChannelType.category),
    }
    cog = _cog()
    restored = run(cog._restore_channels(guild, snapshots))

    assert restored == 3
    names = [c.name for c in guild.created_channels]
    assert "yenikanal" in names
    assert "ses" in names
    assert "kategori" in names


def test_restore_channels_empty_snapshots():
    cog = _cog()
    assert run(cog._restore_channels(FakeGuild(), {})) == 0


def test_restore_roles_skips_existing_restores_missing():
    guild = FakeGuild()
    existing = FakeRole(10, "varolan")
    guild._roles.append(existing)

    snapshots = {
        10: {"name": "varolan", "color": 0, "hoist": False, "mentionable": False, "permissions": 0, "position": 1},
        11: {"name": "yenirole", "color": 255, "hoist": True, "mentionable": True, "permissions": 8, "position": 3},
    }
    cog = _cog()
    restored = run(cog._restore_roles(guild, snapshots))

    assert restored == 1
    assert guild.created_roles[0].name == "yenirole"


def test_restore_roles_empty_snapshots():
    cog = _cog()
    assert run(cog._restore_roles(FakeGuild(), {})) == 0


def test_serialize_overwrite_role_target():
    target = FakeRole(7, "hedef")
    allow = discord.Permissions(8)
    deny = discord.Permissions(0)
    ov = discord.PermissionOverwrite.from_pair(allow, deny)

    data = _serialize_overwrite(target, ov)

    assert data["target_id"] == 7
    assert data["type"] == 0  # rol
    assert data["allow"] == 8
    assert data["deny"] == 0


def test_serialize_overwrite_member_target():
    member = FakeUser(123)
    allow = discord.Permissions(1024)
    deny = discord.Permissions(0)
    ov = discord.PermissionOverwrite.from_pair(allow, deny)

    data = _serialize_overwrite(member, ov)

    assert data["target_id"] == 123
    assert data["type"] == 1  # üye
    assert data["allow"] == 1024


# ---------------------------------------------------------------------------
# Güvenilir silme kararı (_snapshot_delete_is_trusted)
# ---------------------------------------------------------------------------


def test_snapshot_delete_trusted_when_whitelisted(db):
    run(database.add_whitelist(42, 777))
    guild = FakeGuildWithAudit([FakeAuditEntry(FakeUser(777))])
    cog = _cog(uid=999)
    trusted = run(cog._snapshot_delete_is_trusted(guild, discord.AuditLogAction.channel_delete))
    assert trusted is True


def test_snapshot_delete_untrusted_when_not_whitelisted(db):
    guild = FakeGuildWithAudit([FakeAuditEntry(FakeUser(12345))])
    cog = _cog(uid=999)
    trusted = run(cog._snapshot_delete_is_trusted(guild, discord.AuditLogAction.channel_delete))
    assert trusted is False


def test_snapshot_delete_bot_actor_is_trusted(db):
    guild = FakeGuildWithAudit([FakeAuditEntry(FakeUser(999))])
    cog = _cog(uid=999)
    trusted = run(cog._snapshot_delete_is_trusted(guild, discord.AuditLogAction.role_delete))
    assert trusted is True


def test_snapshot_delete_no_audit_entry_keeps_snapshot(db):
    # Audit log yoksa snapshot korunur (güvenli yön)
    guild = FakeGuildWithAudit([])
    cog = _cog(uid=999)
    trusted = run(cog._snapshot_delete_is_trusted(guild, discord.AuditLogAction.channel_delete))
    assert trusted is False


# ---------------------------------------------------------------------------
# Nuke tetikleme (_track_nuke)
# ---------------------------------------------------------------------------


def test_track_nuke_triggers_lockdown_at_threshold(db):
    cog = _cog()
    cog._cfg = lambda gid: {
        "anti_nuke": {"enabled": True, "threshold": 3, "window_seconds": 10, "auto_unban": False},
    }
    guild = FakeGuildWithAudit([])

    for _ in range(3):
        run(cog._track_nuke(guild))

    assert guild.id in cog.locked


def test_track_nuke_below_threshold_no_lockdown(db):
    cog = _cog()
    cog._cfg = lambda gid: {
        "anti_nuke": {"enabled": True, "threshold": 5, "window_seconds": 10},
    }
    guild = FakeGuildWithAudit([])

    for _ in range(2):
        run(cog._track_nuke(guild))

    assert guild.id not in cog.locked


def test_track_nuke_disabled(db):
    cog = _cog()
    cog._cfg = lambda gid: {"anti_nuke": {"enabled": False}}
    guild = FakeGuildWithAudit([])

    for _ in range(10):
        run(cog._track_nuke(guild))

    assert guild.id not in cog.locked


def test_track_nuke_window_expiry(db):
    """Pencere (0 sn) içinde kalmayan eski olaylar sayılmamalı; eşiğe hiç ulaşılamaz."""
    cog = _cog()
    cog._cfg = lambda gid: {
        "anti_nuke": {"enabled": True, "threshold": 2, "window_seconds": 0, "auto_unban": False},
    }
    guild = FakeGuildWithAudit([])

    for _ in range(10):
        run(cog._track_nuke(guild))

    assert guild.id not in cog.locked
