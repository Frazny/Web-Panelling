"""Tüm komutların (slash + prefix) kanal içi test aracı.

Gercek botla ayni oturumla Discord'a baglanir, tum cog'lar yuklenir ve
her komut sahte bir interaction/ctx ile tek tek calistirilir. Sonuclar
TEST_CHANNEL_ID kanalina mesaj olarak gonderilir.

Guvenlik:
- Gecici SQLite kullanir (gercek data/bot.db'ye dokunmaz).
- config.json'a yazmayi engeller (save_config no-op, sadece okunur kopya).
- config kopyasindan voice_24_7 temizlenir ve levels voice XP kapatilir
  (canli sunucuda yan etki olmamasi icin).
- Sahte guild/uye kullanildigi icin sunucuda hicbir gercek degisiklik olmaz.
- Discord'a bot olarak baglanir, this yuzden gercek bot CALISIRKEN
  calistirilmamalidir (tek token tek oturum).
"""

import asyncio
import copy
import datetime
import inspect
import json
import os
import sys
import tempfile
import types
import typing

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui

TEST_CHANNEL_ID = 1526307664986902669

EXTENSIONS = [
    "cogs.guard",
    "cogs.moderation",
    "cogs.registration",
    "cogs.welcome",
    "cogs.levels",
    "cogs.invites",
    "cogs.tickets",
    "cogs.interface",
    "cogs.music",
    "cogs.economy",
    "cogs.logging",
    "cogs.utility",
    "cogs.rolemenu",
    "cogs.social",
    "cogs.management",
    "cogs.voice_keep",
    "cogs.automod",
    "cogs.emoji",
]

# ---------------------------------------------------------------------------
# Gercek config korumasi
# ---------------------------------------------------------------------------

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(CFG_PATH, "r", encoding="utf-8") as f:
    REAL_CFG = json.load(f)

_cfg_copy = copy.deepcopy(REAL_CFG)
_cfg_copy.pop("voice_24_7", None)
if isinstance(_cfg_copy.get("levels"), dict):
    _cfg_copy["levels"]["enabled"] = False
for _gid, _ov in _cfg_copy.get("guilds", {}).items():
    if isinstance(_ov, dict):
        _ov.pop("voice_24_7", None)
        if isinstance(_ov.get("levels"), dict):
            _ov["levels"]["enabled"] = False


def _safe_load_config():
    return copy.deepcopy(_cfg_copy)


def _safe_save_config(data):
    print("[güvenlik] save_config çağrısı engellendi (config.json korundu)")


database.load_config = _safe_load_config
database.save_config = _safe_save_config
import utils.checks
utils.checks.load_config = _safe_load_config

# ---------------------------------------------------------------------------
# Gecici DB
# ---------------------------------------------------------------------------

_tmp = tempfile.mkdtemp(prefix="komut_test_", dir=os.environ.get("TEMP", "."))
database.DB_PATH = os.path.join(_tmp, "bot.db")


# ---------------------------------------------------------------------------
# Sahte nesneler
# ---------------------------------------------------------------------------


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


class _FakeAvatar:
    url = "https://example.com/avatar.png"

    async def read(self):
        return b"fake"


class _FakeRole:
    def __init__(self, rid=1, name="Rol", position=1):
        self.id = rid
        self.name = name
        self.color = discord.Color(0)
        self.hoist = False
        self.mentionable = False
        self.managed = False
        self.position = position
        self.permissions = discord.Permissions(0)
        self.members = []
        self.mention = f"<@&{rid}>"
        self.guild = None

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= getattr(other, "position", 0)

    async def edit(self, **kw):
        pass

    async def delete(self, **kw):
        pass


class _FakeUser:
    def __init__(self, uid=555, name="TestKullanici"):
        self.id = uid
        self.name = name
        self.display_name = name
        self.display_avatar = _FakeAvatar()
        self.avatar = _FakeAvatar()
        self.banner = None
        self.mention = f"<@{uid}>"
        self.bot = False
        self.joined_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        self.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        self.status = discord.Status.online
        self.activities = []
        self.voice = None
        self.top_role = _FakeRole(2, "Moderator", position=3)
        self.guild_permissions = discord.Permissions(8)
        self.guild = None
        self.roles = []
        self.nick = None
        self.premium_since = None
        self.timed_out_until = None

    def is_timed_out(self):
        return False

    async def add_roles(self, *roles, reason=None):
        pass

    async def remove_roles(self, *roles, reason=None):
        pass

    async def edit(self, **kw):
        pass

    async def timeout(self, *a, **kw):
        pass

    async def kick(self, *a, **kw):
        pass

    async def ban(self, *a, **kw):
        pass

    async def unban(self, *a, **kw):
        pass

    async def move_to(self, *a, **kw):
        pass


class _FakeMessage:
    def __init__(self, channel=None):
        self.id = 1
        self.channel = channel or _FakeChannel()
        self.embeds = []
        self.reactions = []
        self.jump_url = "https://example.com/mesaj"
        self.author = _FakeUser()
        self.content = "test"
        self.guild = None
        self.created_at = datetime.datetime.now(datetime.timezone.utc)

    async def add_reaction(self, emoji):
        pass

    async def edit(self, **kw):
        pass

    async def delete(self):
        pass

    async def clear_reactions(self):
        pass


class _FakeChannel:
    def __init__(self, cid=556, name="test-kanal"):
        self.id = cid
        self.name = name
        self.type = discord.ChannelType.text
        self.mention = f"<#{cid}>"
        self.guild = None
        self.category_id = None
        self.category = None
        self.position = 0
        self.topic = None
        self.nsfw = False
        self.slowmode_delay = 0
        self.overwrites = {}
        self.members = []
        self.voice_states = {}
        self.jump_url = f"https://discord.com/channels/1/{cid}"

    def history(self, **kw):
        return _AsyncIter([])

    async def purge(self, *a, **kw):
        return 0

    async def send(self, **kw):
        return _FakeMessage(self)

    async def edit(self, **kw):
        pass

    async def set_permissions(self, *a, **kw):
        pass

    async def fetch_message(self, message_id, **kw):
        raise discord.NotFound(None, "Mesaj bulunamadı")

    async def delete(self):
        pass


class _FakeGuild:
    def __init__(self, gid=12345):
        self.id = gid
        self.name = "Test Sunucusu"
        self.icon = None
        self.banner = None
        self.description = None
        self.emojis = []
        self.stickers = []
        self.member_count = 1
        self.members = []
        self.roles = [_FakeRole(gid, "@everyone")]
        self.channels = []
        self.text_channels = []
        self.voice_channels = []
        self.categories = []
        self.owner_id = 1
        self.owner = _FakeUser(1, "Sahip")
        self.me = _FakeUser(999, "Bot")
        self.default_role = self.roles[0]
        self.created_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        self.premium_subscription_count = 0
        self.premium_tier = 0
        self.verification_level = discord.VerificationLevel.low
        self.mfa_level = 0
        self.voice_client = None
        self.system_channel = None
        self.rules_channel = None
        self.public_updates_channel = None
        self.afk_channel = None
        self.large = False
        self.max_members = 100
        self.vanity_url_code = None
        self.features = []
        self.explicit_content_filter = discord.ContentFilter.disabled

    def get_member(self, uid):
        return None

    def get_channel(self, cid):
        return None

    def get_role(self, rid):
        return None

    def audit_logs(self, **kw):
        return _AsyncIter([])

    async def create_text_channel(self, name, **kw):
        ch = _FakeChannel(100000 + len(self.channels), name)
        ch.guild = self
        self.channels.append(ch)
        self.text_channels.append(ch)
        return ch

    async def create_voice_channel(self, name, **kw):
        ch = _FakeChannel(200000 + len(self.channels), name)
        ch.type = discord.ChannelType.voice
        ch.guild = self
        self.channels.append(ch)
        self.voice_channels.append(ch)
        return ch

    async def create_category(self, name, **kw):
        ch = _FakeChannel(300000 + len(self.channels), name)
        ch.type = discord.ChannelType.category
        ch.guild = self
        self.channels.append(ch)
        self.categories.append(ch)
        return ch

    async def create_role(self, name, **kw):
        role = _FakeRole(900000 + len(self.roles), name)
        self.roles.append(role)
        return role

    async def create_custom_emoji(self, name, image, reason=None):
        raise discord.HTTPException(None, "sahte emoji olusturma engellendi")

    async def kick(self, *a, **kw):
        pass

    async def ban(self, *a, **kw):
        pass

    async def unban(self, *a, **kw):
        pass

    async def edit(self, **kw):
        pass

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return None


class _FakeResponse:
    def __init__(self):
        self.calls = []
        self.done = False

    async def send_message(self, **kw):
        self.calls.append(("send", kw))
        self.done = True

    async def defer(self, **kw):
        self.calls.append(("defer", kw))
        self.done = True

    def is_done(self):
        return self.done


class _FakeFollowup:
    async def send(self, **kw):
        return _FakeMessage()


class _FakeInteraction:
    def __init__(self):
        self.guild = _FakeGuild()
        self.user = _FakeUser(555, "TestKullanici")
        self.channel = _FakeChannel()
        self.guild_id = self.guild.id
        self.channel_id = self.channel.id
        self.created_at = datetime.datetime.now(datetime.timezone.utc)
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.data = {}
        self.type = discord.InteractionType.application_command

    async def edit_original_response(self, **kw):
        self.response.calls.append(("edit", kw))

    async def original_response(self):
        return _FakeMessage()


class _FakeCtx:
    def __init__(self):
        self.message = _FakeMessage()
        self.guild = _FakeGuild()
        self.author = _FakeUser(555, "TestKullanici")
        self.channel = _FakeChannel()
        self.message.guild = self.guild
        self.message.author = self.author
        self.message.channel = self.channel
        self.prefix = "!"

    async def send(self, content=None, **kw):
        if content is not None:
            kw["content"] = content
        if kw.get("embed") is not None:
            kw["embed"] = ui.apply_animated(kw["embed"], self.guild)
        return _FakeMessage(self.channel)

    async def reply(self, content=None, **kw):
        return await self.send(content, **kw)

    async def defer(self, **kw):
        pass


# ---------------------------------------------------------------------------
# Parametre uretici
# ---------------------------------------------------------------------------


def _value_for(annotation, name):
    if annotation is str:
        return "test"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return True
    if (
        annotation is types.UnionType
        or getattr(annotation, "_name", None) == "Union"
        or getattr(annotation, "__origin__", None) is typing.Union
    ):
        for arg in getattr(annotation, "__args__", ()):
            if arg is not type(None):
                return _value_for(arg, name)
        return None
    if annotation == discord.User:
        return _FakeUser(777, "HedefKullanici")
    if annotation == discord.Member:
        return _FakeUser(777, "HedefKullanici")
    if annotation == discord.Role:
        return _FakeRole(3, "HedefRol", position=2)
    if annotation == discord.TextChannel:
        return _FakeChannel(999, "hedef-kanal")
    s = str(annotation)
    if "Choice" in s and "str" in s:
        return app_commands.Choice(name="test", value="test")
    if "Range" in s or "Annotated" in s:
        return 1
    return "test"


def _build_params(cmd, interaction):
    params = {}
    if hasattr(cmd, "parameters"):
        try:
            sig = inspect.signature(cmd.callback)
        except (ValueError, TypeError):
            sig = None
        if sig is not None:
            for name in list(sig.parameters)[1:]:
                ann = sig.parameters[name].annotation
                params[name] = "test" if ann is inspect.Parameter.empty else _value_for(ann, name)
            return params
    for name, p in (getattr(cmd, "clean_params", {}) or {}).items():
        ann = getattr(p, "annotation", inspect.Parameter.empty)
        if ann is inspect.Parameter.empty:
            params[name] = "test"
        else:
            params[name] = _value_for(ann, name)
    return params


def _cog_for(bot, cmd):
    binding = getattr(cmd, "binding", None)
    if binding is not None:
        if isinstance(binding, commands.Cog):
            return binding
        cog = bot.get_cog(binding.__name__)
        if cog is not None:
            return cog
    qname = getattr(cmd.callback, "__qualname__", "") or ""
    cls = qname.split(".")[0] if qname else ""
    for cog in bot.cogs.values():
        if type(cog).__name__ == cls:
            return cog
    return None


# ---------------------------------------------------------------------------
# Test kosucusu
# ---------------------------------------------------------------------------

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})


async def invoke_guard(name, coro, timeout=25):
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        return True, ""
    except asyncio.TimeoutError:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def _run_one(bot, cmd, cog, label, params, timeout=25):
    inter = _FakeInteraction()
    ok, detail = await invoke_guard(label, cmd.callback(cog, inter, **params), timeout)
    return ok, detail, inter


VARIANTS = {
    "tempban": [{"süre": "5dk"}],
    "tempmute": [{"süre": "5dk"}],
    "cekilis": [{"süre": "5dk"}],
}


async def test_slash_command(bot, cmd, variant_params=None):
    cog = _cog_for(bot, cmd)
    if cog is None:
        record(f"/{cmd.name}", False, "cog bulunamadı")
        return

    if cmd.name == "emojiler":
        for choice in ("kur", "temizle", "liste"):
            inter = _FakeInteraction()
            ok, detail = await invoke_guard(
                f"/emojiler:{choice}",
                cmd.callback(cog, inter, secim=choice),
                timeout=40,
            )
            record(f"/emojiler:{choice}", ok and len(inter.response.calls) > 0, "" if ok else detail)
        return

    if cmd.name == "guard":
        for action in ("lockdown", "unlock", "restore"):
            inter = _FakeInteraction()
            ok, detail = await invoke_guard(
                f"/guard {action}",
                cmd.callback(cog, inter, action=action),
                timeout=30,
            )
            record(f"/guard {action}", ok and len(inter.response.calls) > 0, "" if ok else detail)
        return

    if cmd.name == "wl":
        for action in ("add", "remove", "list"):
            inter = _FakeInteraction()
            kwargs = {"action": action}
            if action != "list":
                kwargs["user"] = _FakeUser(777, "HedefKullanici")
            ok, detail = await invoke_guard(
                f"/wl {action}",
                cmd.callback(cog, inter, **kwargs),
                timeout=30,
            )
            record(f"/wl {action}", ok and len(inter.response.calls) > 0, "" if ok else detail)
        return

    if cmd.name == "bl":
        for action in ("add", "remove", "list"):
            inter = _FakeInteraction()
            kwargs = {"action": action}
            if action != "list":
                kwargs["user"] = _FakeUser(777, "HedefKullanici")
            ok, detail = await invoke_guard(
                f"/bl {action}",
                cmd.callback(cog, inter, **kwargs),
                timeout=30,
            )
            record(f"/bl {action}", ok and len(inter.response.calls) > 0, "" if ok else detail)
        return

    if cmd.name == "protect":
        for action in ("add", "remove", "list"):
            inter = _FakeInteraction()
            kwargs = {"action": action}
            if action != "list":
                kwargs["rol"] = _FakeRole(3, "HedefRol", position=2)
            ok, detail = await invoke_guard(
                f"/protect {action}",
                cmd.callback(cog, inter, **kwargs),
                timeout=30,
            )
            record(f"/protect {action}", ok and len(inter.response.calls) > 0, "" if ok else detail)
        return

    for extra in (variant_params or [None]):
        if cmd.name == "dongu":
            params = {"mod": app_commands.Choice(name="off", value="off")}
        else:
            params = _build_params(cmd, _FakeInteraction())
        if extra:
            params.update(extra)

        inter = _FakeInteraction()
        label = f"/{cmd.name}"
        if extra:
            label += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        ok, detail = await invoke_guard(label, cmd.callback(cog, inter, **params))
        if ok and len(inter.response.calls) == 0:
            record(label, False, "SESSİZ: yanıt üretmedi")
        else:
            record(label, ok, "" if ok else detail)


async def test_prefix_command(bot, cmd):
    ctx = _FakeCtx()
    params = {}
    for name_, p in cmd.clean_params.items():
        if p.annotation is inspect.Parameter.empty:
            continue
        params[name_] = _value_for(p.annotation, name_)
    cb = cmd.callback
    if cmd.cog is not None:
        cb = lambda **kw: cmd.callback(cmd.cog, ctx, **kw)
    ok, detail = await invoke_guard(f"!{cmd.name}", cb(**params))
    record(f"!{cmd.name}", ok, "" if ok else detail)


# ---------------------------------------------------------------------------
# Ana akis
# ---------------------------------------------------------------------------


async def post_results(channel):
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["ok"])
    lines = [f"🧪 **Komut Testi — {passed}/{total} gecti**"]
    for r in RESULTS:
        mark = "✅" if r["ok"] else "❌"
        line = f"{mark} `{r['name']}`"
        if r["detail"]:
            line += f" — {r['detail']}"
        lines.append(line)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_komut_sonuc.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    for ln in lines:
        print(ln)
    batch = ""
    for line in lines:
        if len(batch) + len(line) + 2 > 1950:
            try:
                await channel.send(batch)
            except Exception as e:
                print(f"[gönderim hatası] {type(e).__name__}: {e}")
            batch = ""
        batch += line + "\n"
    if batch:
        try:
            await channel.send(batch)
        except Exception as e:
            print(f"[gönderim hatası] {type(e).__name__}: {e}")
    print(f"SONUÇ: {passed}/{total} gecti")


async def main():
    await database.init_db()
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.all(), help_command=None)

    @bot.event
    async def on_ready():
        print(f"Baglandi: {bot.user}")
        channel = bot.get_channel(TEST_CHANNEL_ID)
        if channel is None:
            print(f"HEDEF KANAL BULUNAMADI: {TEST_CHANNEL_ID}")
            for g in bot.guilds:
                print(f"  sunucu {g.id}: {[(c.id, c.name) for c in g.channels][:8]}")
            await bot.close()
            return
        try:
            await channel.send("🧪 **Komut testi başladı** — tüm slash ve prefix komutlar deneniyor.")

            import utils.emoji_anim
            utils.emoji_anim.build_pack = lambda: []

            for ext in EXTENSIONS:
                try:
                    await bot.load_extension(ext)
                    record(f"cog-yukleme {ext}", True)
                except Exception as e:
                    record(f"cog-yukleme {ext}", False, f"{type(e).__name__}: {e}")

            for cmd in bot.tree.get_commands():
                await test_slash_command(bot, cmd, variant_params=VARIANTS.get(cmd.name))

            for prefix_cmd in bot.commands:
                await test_prefix_command(bot, prefix_cmd)

            await post_results(channel)
        except Exception as e:
            await channel.send(f"❌ **Test çalıştırıcı hatası:** `{type(e).__name__}: {e}`")
            print(f"BEKLENMEYEN HATA: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task() and not task.done():
                    task.cancel()
            await bot.close()

    await bot.start(REAL_CFG["token"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ANA HATA: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()