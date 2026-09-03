import re
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

import database
from database import guild_config
from utils import ui
from utils.checks import is_owner

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.history = defaultdict(deque)
        self.raid_mode = set()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_owner(interaction.user.id):
            return True
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            embed=ui.alert("error", "Bu komutu yalnızca sunucu yöneticileri kullanabilir.", interaction=interaction),
            ephemeral=True,
        )
        return False

    def _cfg(self, guild_id):
        return guild_config(guild_id).get("automod", {})

    def _warn_channel(self, guild):
        ch_id = guild_config(guild.id).get("moderation", {}).get("mod_log_channel", 0)
        return guild.get_channel(int(ch_id)) if ch_id else None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        prefix = guild_config(message.guild.id).get("prefix", "!")
        if message.content.startswith(prefix):
            return
        cfg = self._cfg(message.guild.id)
        if not cfg.get("enabled", True):
            return
        member = message.author
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return
        content = message.content
        triggered = None

        if message.guild.id in self.raid_mode:
            triggered = "raid modu"

        if not triggered:
            words = await database.get_automod_words(message.guild.id)
            lower = content.lower()
            for word in words:
                if re.search(rf"\b{re.escape(word)}\b", lower):
                    triggered = f"yasaklı kelime: `{word}`"
                    break

        if not triggered and cfg.get("max_links", 0):
            if len(URL_RE.findall(content)) > cfg["max_links"]:
                triggered = "çok fazla link"

        if not triggered and cfg.get("max_mentions", 0):
            if len(message.mentions) > cfg["max_mentions"]:
                triggered = "çok fazla etiketleme"

        if not triggered and cfg.get("caps_percent", 0):
            letters = [c for c in content if c.isalpha()]
            if letters and sum(c.isupper() for c in letters) / len(letters) >= cfg["caps_percent"] / 100 and len(letters) >= 5:
                triggered = "aşırı büyük harf"

        if not triggered:
            now = time.time()
            window = cfg.get("spam_window_seconds", 5)
            limit = cfg.get("spam_limit", 5)
            key = (message.guild.id, message.author.id)
            self.history[key].append(now)
            while self.history[key] and now - self.history[key][0] > window:
                self.history[key].popleft()
            if len(self.history[key]) >= limit:
                triggered = "spam"

        if triggered:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            channel = self._warn_channel(message.guild)
            if channel:
                try:
                    await channel.send(
                        f"🛡️ **AutoMod** • {message.author.mention}\n"
                        f"İhlal: {triggered}\n"
                        f"Kanal: {message.channel.mention}\n"
                        f"İçerik: {message.content[:200]}"
                    )
                except discord.Forbidden:
                    pass

    @app_commands.command(name="yasakkelime", description="Yasaklı kelime ekler")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yasakkelime(self, interaction: discord.Interaction, kelime: str):
        await database.add_automod_word(interaction.guild_id, kelime)
        count = len(await database.get_automod_words(interaction.guild_id))
        e = ui.embed(
            "Yasaklı Kelime Eklendi",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🚫",
        )
        e.add_field(name="Kelime", value=f"`{kelime}`", inline=True)
        e.add_field(name="Toplam", value=f"**{count}** kelime", inline=True)
        await ui.animate(interaction, final=e, text="Kaydediliyor", emoji_="🚫", color="success", steps=4, delay=0.14)

    @app_commands.command(name="yasakkelime_sil", description="Yasaklı kelime kaldırır")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yasakkelime_sil(self, interaction: discord.Interaction, kelime: str):
        await database.remove_automod_word(interaction.guild_id, kelime)
        count = len(await database.get_automod_words(interaction.guild_id))
        e = ui.embed(
            "Yasaklı Kelime Kaldırıldı",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🗑️",
        )
        e.add_field(name="Kelime", value=f"`{kelime}`", inline=True)
        e.add_field(name="Kalan", value=f"**{count}** kelime", inline=True)
        await ui.animate(interaction, final=e, text="Siliniyor", emoji_="🗑️", color="success", steps=4, delay=0.14)

    @app_commands.command(name="yasakkelime_liste", description="Yasaklı kelimeleri listeler")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yasakkelime_liste(self, interaction: discord.Interaction):
        words = await database.get_automod_words(interaction.guild_id)
        if not words:
            await interaction.response.send_message(
                embed=ui.alert("success", "Yasaklı kelime yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Yasaklı Kelimeler",
            "**" + ", ".join(f"`{w}`" for w in words) + "**",
            color="error",
            interaction=interaction,
            timestamp=True,
            emoji_="🚫",
        )
        e.add_field(name="Toplam", value=f"**{len(words)}** kelime", inline=True)
        await ui.animate(interaction, final=e, text="Liste getiriliyor", emoji_="🚫", color="error", steps=4, delay=0.14)

    @app_commands.command(name="raid", description="Raid modunu aç/kapat (yeni üyeler otomatik banlanır)")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid(self, interaction: discord.Interaction):
        if interaction.guild.id in self.raid_mode:
            self.raid_mode.discard(interaction.guild.id)
            e = ui.embed(
                "Raid Modu Kapatıldı",
                "Sunucu koruması normale döndü. Yeni üyeler artık otomatik banlanmaz.",
                color="success",
                interaction=interaction,
                timestamp=True,
                emoji_="🟢",
            )
        else:
            self.raid_mode.add(interaction.guild.id)
            e = ui.embed(
                "Raid Modu AÇIK",
                "Sunucuya yeni giren üyeler **otomatik banlanacak!** Kapatmak için tekrar `/raid` yaz.",
                color="error",
                interaction=interaction,
                timestamp=True,
                emoji_="🔴",
            )
        await ui.animate(interaction, final=e, text="Güvenlik güncelleniyor", emoji_="🛡️", color="guard", steps=4, delay=0.15)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id in self.raid_mode:
            try:
                await member.ban(reason="Raid modu: otomatik koruma")
                channel = self._warn_channel(member.guild)
                if channel:
                    await channel.send(f"🛡️ **Raid koruması:** {member.mention} raid modundayken sunucuya girdi ve atıldı.")
            except discord.Forbidden:
                pass


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
