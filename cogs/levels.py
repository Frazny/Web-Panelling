import asyncio
import datetime
import io
import math
from collections import defaultdict

import discord
from discord.ext import commands

import database
from utils import animations
from utils import ui

VOICE_TICK_SECONDS = 60


def xp_for_level(level):
    return 100 * (level ** 2)


def level_from_xp(xp):
    return int(math.sqrt(xp / 100))


class LevelCardButton(discord.ui.View):
    def __init__(self, member):
        super().__init__(timeout=120)
        self.member = member

    @discord.ui.button(label="🔄 Animasyonlu kart", style=discord.ButtonStyle.primary)
    async def on_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.member.id:
            await interaction.followup.send("Bu kart sana ait değil.", ephemeral=True)
            return
        xp = await database.get_xp(self.member.guild.id, self.member.id)
        level = level_from_xp(xp)
        current = xp - xp_for_level(level)
        needed = xp_for_level(level + 1) - xp_for_level(level)
        try:
            avatar = await self.member.display_avatar.read()
            gif = await asyncio.to_thread(
                animations.create_level_gif, avatar, self.member.display_name, level, current, needed
            )
        except Exception:
            await interaction.followup.send("❌ Kart oluşturulamadı.", ephemeral=True)
            return
        await interaction.followup.send(file=discord.File(io.BytesIO(gif), "seviye.gif"))


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = defaultdict(float)
        self._voice_task = None

    def _cfg(self, guild_id):
        return database.guild_config(guild_id).get("levels", {})

    @staticmethod
    def _duration(seconds):
        seconds = int(max(0, seconds))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days} gün")
        if hours:
            parts.append(f"{hours} saat")
        if mins:
            parts.append(f"{mins} dakika")
        if secs:
            parts.append(f"{secs} saniye")
        return ", ".join(parts) or "0 saniye"

    async def _level_channel(self, guild):
        ch_id = await database.get_setting(guild.id, "level_channel", None)
        if not ch_id:
            ch_id = self._cfg(guild.id).get("channel_id", 0)
        return guild.get_channel(int(ch_id)) if ch_id else None

    async def cog_load(self):
        self._voice_task = asyncio.create_task(self._voice_loop())

    async def cog_unload(self):
        if self._voice_task:
            self._voice_task.cancel()

    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(VOICE_TICK_SECONDS)
            for guild in list(self.bot.guilds):
                try:
                    await self._tick_guild(guild)
                except Exception:
                    pass

    async def _tick_guild(self, guild):
        cfg = self._cfg(guild.id)
        if not cfg.get("enabled", True):
            return
        xp_per_tick = cfg.get("xp_per_voice_tick", 10)
        if xp_per_tick <= 0:
            return
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        for member in guild.members:
            if member.bot or member.voice is None:
                continue
            if afk_id and member.voice.channel.id == afk_id:
                continue
            await database.add_voice_seconds(member.guild.id, member.id, VOICE_TICK_SECONDS)
            await self._award_xp(member, xp_per_tick, "voice")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id == self.bot.user.id:
            await self._count_bot_log(message)
            return
        if message.author.bot or message.guild is None:
            return
        cfg = self._cfg(message.guild.id)
        if not cfg.get("enabled", True):
            return
        cooldown = cfg.get("cooldown_seconds", 60)
        now = message.created_at.timestamp()
        if now - self.cooldowns.get((message.guild.id, message.author.id), 0) < cooldown:
            return
        self.cooldowns[(message.guild.id, message.author.id)] = now
        amount = cfg.get("xp_per_message", 15)
        await self._award_xp(message.author, amount, "message")

    async def _count_bot_log(self, message):
        """Yapılandırılmış bot log kanalında botun attığı mesajları sayaça işler."""
        if message.guild is None:
            return
        target = self._cfg(message.guild.id).get("bot_log_channel")
        if not target:
            return
        if message.channel.id != int(target):
            return
        await database.incr_bot_log_count(message.guild.id)

    async def _award_xp(self, member, amount, source):
        if member.bot or member.guild is None:
            return
        cfg = self._cfg(member.guild.id)
        if not cfg.get("enabled", True):
            return
        before = await database.get_xp(member.guild.id, member.id)
        before_level = level_from_xp(before)
        if source == "message":
            await database.add_message_xp(member.guild.id, member.id, amount)
        else:
            await database.add_xp(member.guild.id, member.id, amount)
        after_level = level_from_xp(before + amount)
        if after_level > before_level:
            await self._announce_levelup(member, after_level, source, before + amount)

    async def _announce_levelup(self, member, level, source, total_xp):
        guild = member.guild
        cfg = self._cfg(guild.id)
        level_roles = cfg.get("level_roles", {})
        role = guild.get_role(level_roles.get(str(level), 0))
        if role is not None:
            try:
                await member.add_roles(role, reason=f"{level}. seviye rolü")
            except discord.Forbidden:
                pass

        channel = await self._level_channel(guild)
        if not channel:
            return

        current = total_xp - xp_for_level(level)
        needed = xp_for_level(level + 1) - xp_for_level(level)
        reason = (
            "Ses kanalındaki aktifliğin sayesinde"
            if source == "voice"
            else "Yazdığın mesajlar sayesinde"
        )
        now = datetime.datetime.now()

        gif = None
        try:
            avatar = await member.display_avatar.read()
            gif = await asyncio.to_thread(
                animations.create_level_gif,
                avatar,
                member.display_name,
                level,
                current,
                needed,
            )
        except Exception:
            gif = None

        e = discord.Embed(
            title="🎉 Tebrikler, Seviye Atladın!",
            description=f"{member.mention}\n{reason} **Seviye {level}** oldun! 🚀",
            color=discord.Color(0x58B9FF),
        )
        if gif:
            e.set_image(url="attachment://seviye.gif")
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Seviye", value=f"**{level}**", inline=True)
        e.add_field(name="XP", value=f"{current}/{needed}", inline=True)
        e.add_field(
            name="İlerleme",
            value=f"`{ui.bar(current, needed, width=14)}`",
            inline=False,
        )
        e.set_footer(text=f"{now:%d.%m.%Y %H:%M}")
        ui.apply_animated(e, channel.guild)
        kw = {"embed": e}
        if gif:
            kw["file"] = discord.File(io.BytesIO(gif), "seviye.gif")
        try:
            await channel.send(**kw)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @discord.app_commands.command(name="level", description="Kendi seviyeni görüntüle")
    @discord.app_commands.describe(member="Bakılacak üye (boş bırakılırsa kendin)")
    async def level(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        xp = await database.get_xp(interaction.guild_id, member.id)
        level = level_from_xp(xp)
        current_xp = xp - xp_for_level(level)
        needed = xp_for_level(level + 1) - xp_for_level(level)

        rows = await database.get_level_leaderboard(interaction.guild_id, limit=999999)
        rank = next((i for i, (uid, _) in enumerate(rows, start=1) if uid == member.id), None)

        e = ui.embed(
            "Seviye Kartı",
            description=None,
            color="level",
            interaction=interaction,
            timestamp=True,
            emoji_="⭐",
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Üye", value=member.mention, inline=True)
        e.add_field(name="Seviye", value=f"**{level}**", inline=True)
        e.add_field(name="Sıralama", value=f"#{rank}" if rank else "—", inline=True)
        e.add_field(
            name=f"İlerleme — {current_xp}/{needed} XP",
            value=f"`{ui.bar(current_xp, needed, width=16)}`",
            inline=False,
        )
        stats = await database.get_level_stats(interaction.guild_id, member.id)
        e.add_field(name="📝 Toplam Mesaj", value=f"**{stats['messages']:,}**", inline=True)
        e.add_field(name="🎧 Ses Süresi", value=self._duration(stats["voice_seconds"]), inline=True)
        bot_logs = await database.get_bot_log_count(interaction.guild_id)
        e.add_field(name="🤖 Bot Logları", value=f"**{bot_logs:,}**", inline=True)
        e.add_field(name="Toplam XP", value=f"**{xp:,}**", inline=True)
        e.add_field(name="Sonraki Seviye", value=f"<t:{int(discord.utils.utcnow().timestamp()) + max(1, int(needed / 15)) * 60}:R>" if needed else "—", inline=True)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • ⭐ Seviye Sistemi", icon_url=interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None)
        await ui.animate(
            interaction,
            final=e,
            text="Kart hazırlanıyor",
            emoji_="⭐",
            color="level",
            detail=f"{member.display_name} • Seviye {level}",
            steps=5,
            delay=0.18,
            view=LevelCardButton(member),
        )

    @discord.app_commands.command(name="top", description="En yüksek seviyeli üyeler")
    async def top(self, interaction: discord.Interaction):
        rows = await database.get_level_leaderboard(interaction.guild_id, 10)
        if not rows:
            await interaction.response.send_message(
                embed=ui.alert("error", "Henüz veri yok.", interaction=interaction), ephemeral=True
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        max_xp = max(xp for _, xp in rows)
        lines = []
        for i, (user_id, xp) in enumerate(rows, start=1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"Bilinmeyen ({user_id})"
            mark = medals[i - 1] if i <= 3 else f"`{i}.`"
            lines.append(f"{mark} {name} — **{xp:,}** XP (seviye {level_from_xp(xp)})\n{ui.bar(xp, max_xp, width=12)}")
        e = ui.embed(
            "Seviye Sıralaması",
            "\n\n".join(lines),
            color="gold",
            interaction=interaction,
            timestamp=True,
            emoji_="🏆",
        )
        await ui.animate(interaction, final=e, text="Sıralama yükleniyor", emoji_="🏆", color="gold", steps=4, delay=0.15)


async def setup(bot):
    await bot.add_cog(Levels(bot))
