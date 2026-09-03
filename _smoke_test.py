"""Kanalda tek tek smoke test — genişletilmiş sürüm.

Kullanım:
    python _smoke_test.py

⚠️ ÖNEMLİ: Bot token'ı aynı anda yalnızca TEK oturumu kaldırır.
Bu scripti çalıştırmadan önce gerçek botu DURDUR (örn. baslat.bat
penceresini kapat). Aksi halde ya gerçek botun oturumu düşer ya da
bu script bağlanamaz.

Kapsam (her sonuç 1490389801407348836 kanalına tek tek mesaj olarak gider):
  A) Saf mantık kontrolleri (güvenli hesap makinesi, ticket, ekonomi)
  B) 18 cog'un tek tek yüklenmesi
  C) Gerçek komutların sahte interaction ile tek tek çağrılması
     (/hesapla, /ping, /bakiye, /level, /invites, /komutlar, /8ball,
      /uptime, /gunluk, /top, /toppara)
  D) Guard anti-nuke geri yükleme + güvenilir silme kararı (sahte guild)

Testler yıkıcı değildir: geçici bir SQLite kullanır (gerçek data/bot.db'ye
dokunmaz), sunucu üzerinde hiçbir değişiklik yapmaz. Komutlar sahte bir
interaction ile çalıştırıldığı için Discord'a gerçek istek atmaz.
"""

import asyncio
import datetime
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import discord
from discord.ext import commands

import database

TARGET_CHANNEL_ID = 1490389801407348836

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

DANGEROUS_EXPRESSIONS = [
    'open("config.json")',
    "().__class__",
    "[].__class__.__mro__",
    "__import__('os')",
    "1/0",
    "2**100000",
    "'a'*100",
    "len([])",
]


# ---------------------------------------------------------------------------
# Sahte nesneler (komutları Discord'a bağlanmadan çağırmak için)
# ---------------------------------------------------------------------------


class _FakeAvatar:
    url = "https://example.com/avatar.png"

    async def read(self):
        return b"fake"


class _FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.name = "TestKullanici"
        self.display_name = "TestKullanici"
        self.display_avatar = _FakeAvatar()
        self.mention = f"<@{uid}>"
        self.bot = False
        self.joined_at = None
        self.created_at = None
        self.status = None
        self.roles = []
        self.top_role = None


class _FakeChannel:
    def __init__(self, cid):
        self.id = cid
        self.name = "test-kanali"
        self.mention = f"<#{cid}>"


class _FakeGuild:
    def __init__(self, gid):
        self.id = gid
        self.name = "Test Sunucusu"
        self.icon = None
        self.emojis = []
        self.member_count = 1
        self.members = []
        self.roles = []
        self.channels = []
        self.voice_channels = []
        self.text_channels = []

    def get_member(self, uid):
        return None

    def get_channel(self, cid):
        return None

    def get_role(self, rid):
        return None


class _FakeResponse:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kw):
        self.calls.append(("send", kw))

    async def defer(self, **kw):
        self.calls.append(("defer", kw))

    def is_done(self):
        return False


class _FakeFollowup:
    async def send(self, **kw):
        pass


class _FakeInteraction:
    def __init__(self, guild, user, channel):
        self.guild = guild
        self.user = user
        self.channel = channel
        self.guild_id = guild.id
        self.channel_id = channel.id
        self.created_at = datetime.datetime.now(datetime.timezone.utc)
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.data = {}
        self.type = discord.InteractionType.application_command

    async def edit_original_response(self, **kw):
        self.response.calls.append(("edit", kw))


# Guard testleri için audit log destekli sahte guild
class _FakeAuditEntry:
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


class _AuditGuild(_FakeGuild):
    def __init__(self, gid, entries=None):
        super().__init__(gid)
        self._entries = entries or []

    def audit_logs(self, **kw):
        return _AsyncIter(self._entries)


class _SimpleChannel:
    def __init__(self, cid, name, ctype, category_id=None, position=0,
                 topic=None, nsfw=False, slowmode_delay=0, overwrites=None):
        self.id = cid
        self.name = name
        self.type = ctype
        self.category_id = category_id
        self.position = position
        self.topic = topic
        self.nsfw = nsfw
        self.slowmode_delay = slowmode_delay
        self.overwrites = overwrites or {}


class _RestoreGuild:
    def __init__(self):
        self.id = 4242
        self._channels = []
        self._roles = []
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
        return None

    def get_member(self, uid):
        return None

    async def create_text_channel(self, name, **kw):
        ch = _SimpleChannel(100 + len(self.created_channels), name, discord.ChannelType.text)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_voice_channel(self, name, **kw):
        ch = _SimpleChannel(200 + len(self.created_channels), name, discord.ChannelType.voice)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_category(self, name, **kw):
        ch = _SimpleChannel(300 + len(self.created_channels), name, discord.ChannelType.category)
        self.created_channels.append(ch)
        self._channels.append(ch)
        return ch

    async def create_role(self, name, **kw):
        class _R:
            def __init__(self, rid, n):
                self.id = rid
                self.name = n

            async def edit(self, **k):
                return self

        r = _R(900 + len(self.created_roles), name)
        self.created_roles.append(r)
        self._roles.append(r)
        return r


def _make_interaction(guild_id=12345):
    return _FakeInteraction(_FakeGuild(guild_id), _FakeUser(555), _FakeChannel(1))


# ---------------------------------------------------------------------------
# Kontroller
# ---------------------------------------------------------------------------


async def run_checks(validation_bot):
    from cogs.utility import _safe_eval

    results = []

    def add(name, ok, detail=""):
        results.append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})

    # --- A) Saf mantık: güvenli hesap makinesi ---
    try:
        for expr, expected in [("2+3*4", 14), ("(1+2)**2", 9), ("-5+3", -2), ("7//2", 3), ("7%2", 1)]:
            got = _safe_eval(expr)
            if got != expected:
                raise AssertionError(f"{expr} -> {got} (beklenen {expected})")
        add("hesapla güvenli çözücü — geçerli ifadeler", True)
    except Exception as e:
        add("hesapla güvenli çözücü — geçerli ifadeler", False, repr(e))

    for expr in DANGEROUS_EXPRESSIONS:
        try:
            _safe_eval(expr)
            add(f"hesapla TEHLİKELİ ifade reddedildi: `{expr}`", False, "ifade geçti — AÇIK!")
        except Exception:
            add(f"hesapla TEHLİKELİ ifade reddedildi: `{expr}`", True)

    # --- A) Açık ticket sınırı ---
    try:
        assert await database.get_user_open_ticket(1, 2) is None
        await database.create_ticket(1, 555, 2)
        assert await database.get_user_open_ticket(1, 2) == 555
        await database.close_ticket(1, 555)
        assert await database.get_user_open_ticket(1, 2) is None
        add("ticket sınırı — get_user_open_ticket", True)
    except Exception as e:
        add("ticket sınırı — get_user_open_ticket", False, repr(e))

    # --- A) Ekonomi atomik ekleme ---
    try:
        new = await database.add_balance(1, 2, 100)
        assert new == 100
        await database.set_balance(1, 2, 300)
        assert await database.add_balance(1, 2, 100) == 400
        add("ekonomi — atomik add_balance", True)
    except Exception as e:
        add("ekonomi — atomik add_balance", False, repr(e))

    # --- B) Tüm cog'ların tek tek yüklenmesi ---
    for ext in EXTENSIONS:
        try:
            await validation_bot.load_extension(ext)
            add(f"cog yükleme — {ext}", True)
        except Exception as e:
            add(f"cog yükleme — {ext}", False, repr(e))

    # --- C) Gerçek komutlar (sahte interaction ile, tek tek) ---
    async def invoke(name, coro, inter=None):
        try:
            before = len(inter.response.calls) if inter else 0
            await coro()
            if inter is not None and len(inter.response.calls) <= before:
                add(f"komut — {name}", False, "komut yanıt üretmedi (sessiz dönüş)")
            else:
                add(f"komut — {name}", True)
        except Exception as e:
            add(f"komut — {name}", False, f"{type(e).__name__}: {e}")

    ut = validation_bot.cogs["Utility"]
    ec = validation_bot.cogs["Economy"]
    lv = validation_bot.cogs["Levels"]
    iv = validation_bot.cogs["Invites"]
    itf = validation_bot.cogs["Interface"]

    inter = _make_interaction()

    await invoke("hesapla (2+2*3)", ut.hesapla(inter, "2+2*3"), inter)
    await invoke("hesapla (2**10)", ut.hesapla(inter, "2**10"), inter)
    await invoke("hesapla (güvenli: x+1 hata)", ut.hesapla(inter, "x+1"), inter)
    await invoke("hesapla (güvenli: 2**100000 hata)", ut.hesapla(inter, "2**100000"), inter)
    await invoke("ping", ut.ping(inter), inter)
    await invoke("uptime", ut.uptime(inter), inter)
    await invoke("8ball", ut.eightball(inter, "Test sorusu?"), inter)
    await invoke("bakiye", ec.bakiye(inter), inter)
    await invoke("gunluk", ec.gunluk(inter), inter)
    await invoke("toppara", ec.toppara(inter), inter)
    await invoke("level", lv.level(inter), inter)
    await invoke("top", lv.top(inter), inter)
    await invoke("invites", iv.invites(inter), inter)
    await invoke("komutlar", itf.komutlar_slash(inter), inter)

    # --- D) Guard anti-nuke geri yükleme (sahte guild ile) ---
    from cogs.guard import Guard

    class _GuardBot:
        def __init__(self):
            self.user = _FakeUser(999)

    cog = Guard(_GuardBot())
    guild = _RestoreGuild()
    snapshots = {
        11: {"name": "yenikanal", "type": discord.ChannelType.text.value, "position": 0,
             "topic": None, "nsfw": False, "slowmode_delay": 0, "overwrites": [], "category_id": None},
        12: {"name": "yenirol", "type": 0},
    }
    try:
        restored = await cog._restore_channels(guild, {11: snapshots[11]})
        assert restored == 1
        assert any(c.name == "yenikanal" for c in guild.created_channels)
        add("guard — kanal geri yükleme", True)
    except Exception as e:
        add("guard — kanal geri yükleme", False, repr(e))

    try:
        restored = await cog._restore_roles(guild, {12: {"name": "yenirol", "color": 0, "hoist": False,
                                                          "mentionable": False, "permissions": 0, "position": 1}})
        assert restored == 1
        add("guard — rol geri yükleme", True)
    except Exception as e:
        add("guard — rol geri yükleme", False, repr(e))

    # Güvenilir silme kararı: whitelist'li aktör → snapshot korunmaz, saldırgan → korunur
    import utils.checks as checks
    checks.load_config = lambda: {}  # config.json bağımsızlığı
    try:
        await database.add_whitelist(4242, 777)
        trusted_guild = _AuditGuild(4242, [_FakeAuditEntry(_FakeUser(777))])
        trusted = await cog._snapshot_delete_is_trusted(trusted_guild, discord.AuditLogAction.channel_delete)
        assert trusted is True
        add("guard — whitelist silmesi snapshot'ı temizler", True)
    except Exception as e:
        add("guard — whitelist silmesi snapshot'ı temizler", False, repr(e))

    try:
        evil_guild = _AuditGuild(4242, [_FakeAuditEntry(_FakeUser(31337))])
        trusted = await cog._snapshot_delete_is_trusted(evil_guild, discord.AuditLogAction.channel_delete)
        assert trusted is False
        add("guard — şüpheli silmede snapshot korunur", True)
    except Exception as e:
        add("guard — şüpheli silmede snapshot korunur", False, repr(e))

    return results


async def post_results(results):
    cfg = database.load_config()
    token = cfg["token"]

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    @bot.event
    async def on_ready():
        print(f"Giriş yapıldı: {bot.user}")
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            print(f"Hedef kanal bulunamadı: {TARGET_CHANNEL_ID}")
            await bot.close()
            return
        send_errors = 0

        async def send(text):
            nonlocal send_errors
            try:
                await channel.send(text)
            except Exception as e:
                send_errors += 1
                print(f"Mesaj gönderilemedi: {type(e).__name__}: {e}")

        try:
            await send("🧪 **Smoke test başlıyor** — kod düzeltmeleri sonrası kontroller")
            passed = 0
            for r in results:
                mark = "✅" if r["ok"] else "❌"
                line = f"{mark} **{r['name']}**"
                if r["detail"]:
                    line += f" — `{r['detail']}`"
                await send(line)
                if r["ok"]:
                    passed += 1
                await asyncio.sleep(0.6)
            tail = ""
            if send_errors:
                tail = f" ⚠️ ({send_errors} mesaj kanala iletilemedi)"
            await send(f"📊 **Sonuç:** {passed}/{len(results)} test geçti{tail}")
            await send(
                "ℹ️ Uçtan uca (gerçek Discord) testi için botu çalıştırıp kanalda "
                "manuel deneyebilirsin (ör. `/hesapla 2+2`, `!ping`)."
            )
        finally:
            await bot.close()

    await bot.start(token)


async def main():
    print("[1/3] Geçici veritabanı kuruluyor…")
    tmpdir = tempfile.mkdtemp(prefix="smoke_")
    database.DB_PATH = os.path.join(tmpdir, "smoke.db")
    await database.init_db()

    print("[2/3] Kontroller çalıştırılıyor (cog yükleme + komutlar + guard)…")
    validation_bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
    results = await run_checks(validation_bot)

    print(f"[3/3] {len(results)} sonuç kanala gönderiliyor ({TARGET_CHANNEL_ID})…")
    await post_results(results)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except FileNotFoundError:
        print("config.json bulunamadı. Botun çalıştığı dizinde olduğundan emin ol.")
    except KeyError as e:
        print(f"config.json içinde eksik anahtar: {e}")
    except Exception as e:
        print(f"Beklenmeyen hata: {type(e).__name__}: {e}")
