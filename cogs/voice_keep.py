import asyncio
import time

import discord
from discord.ext import commands

import database

WATCH_INTERVAL = 45

# Atılma / başarısız bağlantı sonrası yeniden deneme gecikmeleri (saniye).
# Otomatik bağlanma özelliği durur; sadece tekrar denemeler arasına kademeli
# bekleme eklenir (sonsuz kick döngüsünde spam'i önler).
RETRY_DELAYS = (15, 15, 60, 60, 60, 300, 300)


class VoiceKeep(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self._retry = {}

    def _get_retry(self, guild_id):
        return self._retry.setdefault(guild_id, {"fails": 0, "next_try": 0.0})

    @staticmethod
    def _backoff_delay(fails):
        if fails <= 0:
            return 0
        idx = min(fails - 1, len(RETRY_DELAYS) - 1)
        return RETRY_DELAYS[idx]

    def _mark_fail(self, guild_id):
        r = self._get_retry(guild_id)
        r["fails"] += 1
        r["next_try"] = time.monotonic() + self._backoff_delay(r["fails"])

    def _mark_ok(self, guild_id):
        r = self._get_retry(guild_id)
        r["fails"] = 0
        r["next_try"] = 0.0

    def _allowed(self, guild_id):
        return time.monotonic() >= self._get_retry(guild_id)["next_try"]

    def _target(self, guild):
        cfg = database.guild_config(guild.id)
        vc = cfg.get("voice_24_7") or {}
        if not vc.get("enabled"):
            return None
        try:
            ch = guild.get_channel(int(vc["channel_id"]))
        except (KeyError, TypeError, ValueError):
            return None
        return ch if isinstance(ch, discord.VoiceChannel) else None

    async def _music_busy(self, guild):
        """Müzik cogu şu an bu sunucuda şarkı çalıyorsa True.

        Böylece 7/24 hedef kanala bağlanma ile müzik çalma birbiriyle
        çakışmaz: müzik çalarken VoiceKeep dokunmaz, müzik bitince
        hedef kanala dönüşü sağlar."""
        try:
            vc = guild.voice_client
            if vc and (vc.is_playing() or vc.is_paused()):
                return True
        except Exception:
            pass
        cog = self.bot.get_cog("Music")
        state_fn = getattr(cog, "_state", None) if cog else None
        if state_fn is None:
            return False
        try:
            st = state_fn(guild.id)
            return st["current"] is not None or bool(st["queue"])
        except Exception:
            return False

    async def _ensure_connected(self, guild):
        target = self._target(guild)
        if not target:
            return
        if not self._allowed(guild.id):
            return
        if await self._music_busy(guild):
            return
        async with self._lock:
            vc = guild.voice_client
            if vc and vc.is_connected():
                # Müzik çalmıyorken bile mevcut bağlantıyı asla koparma;
                # müzik sistemi hedefe kendi döner. Yanlışlıkla çalışan
                # bir müziği kesmemek için burada dokunmadan dön.
                return
            for attempt in range(5):
                try:
                    await target.connect(self_mute=True, self_deaf=True, reconnect=False, timeout=20)
                    self._mark_ok(guild.id)
                    print(f"[VoiceKeep] Bağlandı: {guild.name} / {target.name}")
                    return
                except Exception as e:
                    print(f"[VoiceKeep] Bağlantı hatası ({attempt + 1}/5) {guild.name}: {type(e).__name__}")
                    await asyncio.sleep(5)
            self._mark_fail(guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(30)
        for guild in self.bot.guilds:
            await self._ensure_connected(guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            self._mark_fail(member.guild.id)
            print(f"[VoiceKeep] Bot sesten çıkarıldı, yeniden bağlanılıyor: {member.guild.name}")
            await self._ensure_connected(member.guild)

    async def _watch_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(WATCH_INTERVAL)
        while True:
            try:
                for guild in self.bot.guilds:
                    if not self._target(guild):
                        continue
                    vc = guild.voice_client
                    if not vc or not vc.is_connected():
                        await self._ensure_connected(guild)
            except Exception:
                pass
            await asyncio.sleep(WATCH_INTERVAL)

    async def cog_load(self):
        asyncio.create_task(self._watch_loop())


async def setup(bot):
    await bot.add_cog(VoiceKeep(bot))