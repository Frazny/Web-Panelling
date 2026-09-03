import asyncio
import logging
import time
from collections import defaultdict, deque

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui

logger = logging.getLogger("ai_chat")

BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-flash-0731"
MODEL_NAME = "DeepSeek V4 Flash"

DEFAULT_SYSTEM_PROMPT = (
    "Sen 'Frazny' tarafından geliştirilen Türkçe bir Discord yardım asistanısın. "
    "Mesajlara kısa, samimi ve net cevaplar ver. Türkçe yazım kurallarına dikkat et."
)


def _read_ai(guild_id):
    return database.guild_config(guild_id).get("ai", {})


def _write_ai(guild_id, key, value):
    cfg = database.load_config()
    section = cfg.setdefault("guilds", {}).setdefault(str(guild_id), {})
    ai = section.setdefault("ai", {})
    ai[key] = value
    database.save_config(cfg)


def _split(text, limit=2000):
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return parts


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._buffer = defaultdict(lambda: deque(maxlen=12))
        self._cooldowns = {}
        self._locks = {}

    def _cfg(self, guild_id):
        return _read_ai(guild_id)

    def _lock(self, guild_id, user_id):
        key = (guild_id, user_id)
        return self._locks.setdefault(key, asyncio.Lock())

    def _should_respond(self, message, cfg):
        trigger = cfg.get("trigger", "mention")
        if trigger == "all":
            return True
        if trigger == "channel":
            ch_id = cfg.get("channel_id") or 0
            return message.channel.id == int(ch_id)
        if trigger == "reply":
            ref = message.reference
            resolved = getattr(ref, "resolved", None) if ref else None
            if resolved is not None and getattr(resolved, "author", None):
                return resolved.author.id == self.bot.user.id
            return False
        return self.bot.user in message.mentions

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        prefix = database.guild_config(message.guild.id).get("prefix", "!")
        content = message.content.strip()
        if not content or content.startswith(prefix):
            return
        cfg = self._cfg(message.guild.id)
        if not cfg.get("enabled", True):
            return
        if not self._should_respond(message, cfg):
            return
        cooldown = float(cfg.get("cooldown_seconds", 5))
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if now - self._cooldowns.get(key, 0) < cooldown:
            return
        self._cooldowns[key] = now
        async with self._lock(*key):
            await self._handle(message, cfg, content)

    async def _handle(self, message, cfg, content):
        clean = (
            content.replace(f"<@{self.bot.user.id}>", "")
            .replace(f"<@!{self.bot.user.id}>", "")
            .strip()
        )
        if not clean:
            clean = content
        buf = self._buffer[(message.guild.id, message.channel.id)]
        buf.append({"role": "user", "content": f"{message.author.display_name}: {clean}"})
        try:
            async with message.channel.typing():
                reply = await self._ask(cfg, buf)
        except Exception as e:
            logger.warning(
                "AI istegi basarisiz: type=%s repr=%r",
                type(e).__name__,
                e,
            )
            return
        if not reply:
            return
        buf.append({"role": "assistant", "content": reply})
        chunks = _split(reply)
        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    await message.reply(embed=self._reply_embed(message.guild, chunk))
                else:
                    await message.channel.send(embed=self._reply_embed(message.guild, chunk))
            except discord.HTTPException:
                break

    async def _ask(self, cfg, buf):
        api_key = cfg.get("api_key") or ""
        model = cfg.get("model") or DEFAULT_MODEL
        system = cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        if not api_key:
            return "API anahtarı ayarlanmamış. `/ai durum` ile kontrol et."

        messages = [{"role": "system", "content": system}] + list(buf)
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BASE_URL, json=payload, headers=headers) as resp:
                data = await resp.json(content_type=None)
        if resp.status != 200:
            logger.warning("AI API %s: %s", resp.status, str(data)[:300])
            return self._api_error(resp.status)
        choices = data.get("choices") or []
        if not choices:
            return "Cevap alınamadı."
        text = (choices[0].get("message") or {}).get("content") or ""
        if not text.strip():
            text = (choices[0].get("message") or {}).get("reasoning_content") or ""
        return text.strip() or "Cevap alınamadı."

    @staticmethod
    def _api_error(status):
        if status == 401:
            return "API anahtarı geçersiz. Yönetici `/ai durum` ile kontrol etsin."
        if status == 429:
            return "AI servisi yoğun, az sonra tekrar dene."
        if status >= 500:
            return "AI servisi şu an yanıt vermiyor, az sonra tekrar dene."
        return f"Bir hata oluştu (HTTP {status})."

    def _reply_embed(self, guild, text):
        e = discord.Embed(description=text, color=discord.Color(0x5865F2))
        e.set_author(name=MODEL_NAME, icon_url=self.bot.user.display_avatar.url)
        e.set_footer(text=f"🤖 {MODEL_NAME}")
        return e

    @staticmethod
    def _trigger_label(trigger):
        return {
            "mention": "Bot etiketlenince",
            "reply": "Bota cevap verilince",
            "all": "Tüm mesajlara",
            "channel": "Belirli kanalda",
        }.get(trigger, trigger)

    ai_group = app_commands.Group(name="ai", description="Yapay zeka sohbet ayarları")

    @ai_group.command(name="durum", description="AI sohbet ayarlarını gösterir")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai_durum(self, interaction: discord.Interaction):
        cfg = self._cfg(interaction.guild_id)
        enabled = cfg.get("enabled", True)
        channel_id = cfg.get("channel_id") or 0
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        has_key = bool(cfg.get("api_key"))
        e = ui.embed(
            "AI Sohbet",
            description=None,
            color="purple",
            interaction=interaction,
            timestamp=True,
            emoji_="🤖",
        )
        e.add_field(name="Durum", value="🟢 Açık" if enabled else "🔴 Kapalı", inline=True)
        e.add_field(name="Tetikleme", value=self._trigger_label(cfg.get("trigger", "mention")), inline=True)
        e.add_field(name="Kanal", value=channel.mention if channel else "—", inline=True)
        e.add_field(name="Model", value=f"`{cfg.get('model') or DEFAULT_MODEL}`", inline=True)
        e.add_field(name="API Anahtarı", value="✔ Ayarlı" if has_key else "❌ Eksik", inline=True)
        e.add_field(name="Soğuma", value=f"{cfg.get('cooldown_seconds', 5)} sn", inline=True)
        await ui.animate(interaction, final=e, text="Durum getiriliyor", emoji_="🤖", color="purple", steps=4, delay=0.14)

    @ai_group.command(name="acik", description="AI sohbeti açar")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai_acik(self, interaction: discord.Interaction):
        _write_ai(interaction.guild_id, "enabled", True)
        e = ui.embed(
            "AI Sohbet Açıldı",
            "Artık mesajlara cevap veriyorum.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🤖",
        )
        await ui.animate(interaction, final=e, text="Açılıyor", emoji_="🤖", color="success", steps=4, delay=0.14)

    @ai_group.command(name="kapat", description="AI sohbeti kapatır")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai_kapat(self, interaction: discord.Interaction):
        _write_ai(interaction.guild_id, "enabled", False)
        e = ui.embed(
            "AI Sohbet Kapatıldı",
            "Artık mesajlara cevap vermeyeceğim.",
            color="error",
            interaction=interaction,
            timestamp=True,
            emoji_="🤖",
        )
        await ui.animate(interaction, final=e, text="Kapatılıyor", emoji_="🤖", color="error", steps=4, delay=0.14)

    @ai_group.command(name="mod", description="Cevap verme modunu ayarlar")
    @app_commands.choices(secenek=[
        app_commands.Choice(name="Bot etiketlenince", value="mention"),
        app_commands.Choice(name="Bota cevap verilince", value="reply"),
        app_commands.Choice(name="Tüm mesajlara", value="all"),
        app_commands.Choice(name="Belirli kanalda", value="channel"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai_mod(self, interaction: discord.Interaction, secenek: app_commands.Choice[str]):
        _write_ai(interaction.guild_id, "trigger", secenek.value)
        e = ui.embed(
            "AI Modu Güncellendi",
            f"Tetikleme: **{self._trigger_label(secenek.value)}**",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🤖",
        )
        await ui.animate(interaction, final=e, text="Mod ayarlanıyor", emoji_="🤖", color="info", steps=4, delay=0.14)

    @ai_group.command(name="kanal", description="'Belirli kanalda' modu için kanalı ayarlar")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai_kanal(self, interaction: discord.Interaction, kanal: discord.TextChannel):
        _write_ai(interaction.guild_id, "channel_id", kanal.id)
        if self._cfg(interaction.guild_id).get("trigger") != "channel":
            _write_ai(interaction.guild_id, "trigger", "channel")
        e = ui.embed(
            "AI Kanalı Ayarlandı",
            f"Yalnızca {kanal.mention} kanalında cevap vereceğim.",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🤖",
        )
        await ui.animate(interaction, final=e, text="Kanal ayarlanıyor", emoji_="🤖", color="info", steps=4, delay=0.14)


async def setup(bot):
    await bot.add_cog(AIChat(bot))
