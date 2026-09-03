import asyncio
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui
from utils.checks import is_owner

MUTED_ROLE_NAME = "Susturuldu"

SAYAC_PATTERN = re.compile(
    r"^(?P<label>\S*\s*)?(?P<kind>Toplam|İnsan|Bot)\s*:\s*\d+.*$", re.IGNORECASE
)


async def _apply_mute_overwrites(guild, role):
    """Susturma rolünün tüm kanallarda mesaj/konuşma iznini kapatır."""
    for channel in guild.channels:
        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel)):
            try:
                await channel.set_permissions(role, send_messages=False, speak=False)
            except discord.Forbidden:
                pass


async def _clear_mute_overwrites(guild, role):
    """Susturma rolünün kanal overwrite'larını temizler."""
    for channel in guild.channels:
        try:
            await channel.set_permissions(role, overwrite=None)
        except discord.Forbidden:
            pass


class PunishmentLoop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    async def cog_load(self):
        self.task = asyncio.create_task(self._loop())

    async def cog_unload(self):
        if self.task:
            self.task.cancel()

    async def _loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    for kind in ("tempmute", "tempban"):
                        for uid, until, _reason in await database.get_active_punishments(guild.id, kind):
                            if until > int(time.time()):
                                continue
                            member = guild.get_member(uid)
                            if kind == "tempmute":
                                muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
                                if member and muted_role:
                                    try:
                                        await member.remove_roles(muted_role)
                                    except discord.Forbidden:
                                        pass
                                if muted_role and not any(
                                    m for m in guild.members if muted_role in m.roles
                                ):
                                    await _clear_mute_overwrites(guild, muted_role)
                            elif kind == "tempban":
                                try:
                                    await guild.unban(discord.Object(id=uid), reason="Süre doldu")
                                except (discord.Forbidden, discord.NotFound):
                                    pass
                            await database.remove_punishment(guild.id, uid, kind)
            except Exception:
                pass
            await asyncio.sleep(10)


class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.muted_role_name = MUTED_ROLE_NAME
        self.locked = set()
        self._sayac_task = None

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

    async def cog_load(self):
        self._sayac_task = asyncio.create_task(self._sayac_loop())

    async def cog_unload(self):
        if self._sayac_task:
            self._sayac_task.cancel()

    async def _update_sayac(self, guild):
        """Sunucudaki üye sayacı kanallarını (Toplam/İnsan/Bot) anlık günceller."""
        total = guild.member_count
        humans = len([m for m in guild.members if not m.bot])
        bots = total - humans
        for channel in guild.voice_channels:
            m = SAYAC_PATTERN.match(channel.name)
            if not m:
                continue
            kind = m.group("kind")
            label = m.group("label") or ""
            key = kind.replace("İ", "i").replace("ı", "i").lower()
            value = {"toplam": total, "insan": humans, "bot": bots}[key]
            new = f"{label}{kind}: {value}".strip()
            if channel.name != new:
                try:
                    await channel.edit(name=new)
                except discord.HTTPException:
                    pass

    async def _sayac_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    await self._update_sayac(guild)
            except Exception:
                pass
            await asyncio.sleep(600)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self._update_sayac(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self._update_sayac(member.guild)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self._update_sayac(guild)

    async def _ensure_muted_role(self, guild):
        role = discord.utils.get(guild.roles, name=self.muted_role_name)
        if not role:
            role = await guild.create_role(name=self.muted_role_name, reason="Tempmute için otomatik oluşturuldu")
        return role

    @app_commands.command(name="slowmode", description="Kanala yavaş mod ayarlar (saniye)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, saniye: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=saniye)
        e = ui.embed(
            "Yavaş Mod",
            f"{interaction.channel.mention} kanalında yavaş mod ayarlandı.",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🐌",
        )
        e.add_field(name="Süre", value=f"**{saniye}** saniye" if saniye else "**Kapalı**", inline=True)
        e.add_field(name="Kanal", value=interaction.channel.mention, inline=True)
        await ui.animate(interaction, final=e, text="Uygulanıyor", emoji_="🐌", color="info", steps=4, delay=0.14)

    @app_commands.command(name="kilit", description="Kanalı herkese kilitler")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def kilit(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        self.locked.add(interaction.channel.id)
        e = ui.embed(
            "Kanal Kilitlendi",
            f"{interaction.channel.mention} kanalı artık kilitli. Yetkili olmayan üyeler mesaj gönderemez.",
            color="error",
            interaction=interaction,
            timestamp=True,
            emoji_="🔒",
        )
        e.add_field(name="Kanal", value=interaction.channel.mention, inline=True)
        e.add_field(name="Açmak İçin", value="`/kilitac`", inline=True)
        await ui.animate(interaction, final=e, text="Kanal kilitleniyor", emoji_="🔒", color="error", steps=4, delay=0.14)

    @app_commands.command(name="kilitac", description="Kanal kilidini açar")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def kilitac(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None)
        self.locked.discard(interaction.channel.id)
        e = ui.embed(
            "Kanal Kilidi Açıldı",
            f"{interaction.channel.mention} kanalında mesaj gönderimi yeniden açık.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🔓",
        )
        e.add_field(name="Kanal", value=interaction.channel.mention, inline=True)
        await ui.animate(interaction, final=e, text="Kilit açılıyor", emoji_="🔓", color="success", steps=4, delay=0.14)

    @app_commands.command(name="tempban", description="Geçici ban uygular")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban(self, interaction: discord.Interaction, uye: discord.Member, süre: str, sebep: str | None = None):
        units = {"s": 1, "dk": 60, "sa": 3600, "g": 86400}
        try:
            amount = int("".join(c for c in süre if c.isdigit()))
            unit = "".join(c for c in süre if not c.isdigit()).lower()
            seconds = amount * units.get(unit, 60)
        except Exception:
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz süre. Örn: `1sa`, `2g`, `30dk`", interaction=interaction),
                ephemeral=True,
            )
            return
        until = int(time.time()) + seconds
        reason = sebep or "Belirtilmedi"
        try:
            await uye.ban(reason=f"{interaction.user}: {reason} (tempban)")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu üyeyi banlayamıyorum.", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Geçici ban uygulanıyor",
            emoji_="🔨",
            color="error",
            detail=f"{uye.mention} • {ui.countdown(seconds)}",
            steps=5,
            delay=0.18,
        )
        await database.add_punishment(interaction.guild_id, uye.id, "tempban", until, reason)
        e = ui.embed(
            "Geçici Ban",
            f"{uye.mention} geçici olarak banlandı.",
            color="error",
            interaction=interaction,
            timestamp=True,
            emoji_="🔨",
        )
        e.add_field(name="Süre", value=f"**{ui.countdown(seconds)}**", inline=True)
        e.add_field(name="Bitiş", value=f"<t:{until}:R>", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=False)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="tempmute", description="Geçici susturma uygular")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def tempmute(self, interaction: discord.Interaction, uye: discord.Member, süre: str, sebep: str | None = None):
        units = {"s": 1, "dk": 60, "sa": 3600, "g": 86400}
        try:
            amount = int("".join(c for c in süre if c.isdigit()))
            unit = "".join(c for c in süre if not c.isdigit()).lower()
            seconds = amount * units.get(unit, 60)
        except Exception:
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz süre. Örn: `1sa`, `2g`, `30dk`", interaction=interaction),
                ephemeral=True,
            )
            return
        until = int(time.time()) + seconds
        reason = sebep or "Belirtilmedi"
        role = await self._ensure_muted_role(interaction.guild)
        try:
            await uye.add_roles(role, reason=f"{interaction.user}: {reason} (tempmute)")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu üyeyi susturamıyorum.", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Geçici susturma uygulanıyor",
            emoji_="🤐",
            color="warn",
            detail=f"{uye.mention} • {ui.countdown(seconds)}",
            steps=5,
            delay=0.18,
        )
        await database.add_punishment(interaction.guild_id, uye.id, "tempmute", until, reason)
        await _apply_mute_overwrites(interaction.guild, role)
        e = ui.embed(
            "Geçici Susturma",
            f"{uye.mention} geçici olarak susturuldu.",
            color="warn",
            interaction=interaction,
            timestamp=True,
            emoji_="🤐",
        )
        e.add_field(name="Süre", value=f"**{ui.countdown(seconds)}**", inline=True)
        e.add_field(name="Bitiş", value=f"<t:{until}:R>", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=False)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="sayac", description="Üye sayacı kanalları oluşturur")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def sayac(self, interaction: discord.Interaction, kategori: discord.CategoryChannel | None = None):
        cat = kategori or interaction.channel.category or await interaction.guild.create_category("📊 Sayaçlar")
        members = interaction.guild.member_count
        humans = len([m for m in interaction.guild.members if not m.bot])
        bots = members - humans
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Sayaç kanalları oluşturuluyor",
            emoji_="📊",
            color="teal",
            detail=f"{cat.name} kategorisi",
            steps=6,
            delay=0.18,
        )
        for name in [f"👥 Toplam: {members}", f"🧑 İnsan: {humans}", f"🤖 Bot: {bots}"]:
            await interaction.guild.create_voice_channel(name, category=cat)
        e = ui.embed(
            "Sayaç Kanalları",
            f"**{cat.name}** kategorisinde sayaç kanalları oluşturuldu.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="📊",
        )
        e.add_field(name="Toplam", value=f"**{members}**", inline=True)
        e.add_field(name="İnsan", value=f"**{humans}**", inline=True)
        e.add_field(name="Bot", value=f"**{bots}**", inline=True)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Otomatik güncellenir (üye giriş/çıkış/kick)")
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="duyuru", description="Duyuru embed'i gönderir")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def duyuru(self, interaction: discord.Interaction, kanal: discord.TextChannel, başlık: str, içerik: str):
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Duyuru gönderiliyor",
            emoji_="📢",
            color="info",
            detail=kanal.mention,
            steps=5,
            delay=0.16,
        )
        embed = discord.Embed(
            title=f"📢 {başlık[:256]}",
            description=içerik[:4000],
            color=discord.Color(ui.COLORS["info"]),
            timestamp=interaction.created_at,
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=interaction.guild.name if interaction.guild else None)
        ui.apply_animated(embed, interaction.guild)
        await kanal.send(embed=embed)
        e = ui.embed(
            "Duyuru Gönderildi",
            f"Duyuru **{kanal.mention}** kanalına iletildi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="📢",
        )
        e.add_field(name="Başlık", value=f"```{başlık[:256]}```", inline=False)
        e.add_field(name="Kanal", value=kanal.mention, inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)


async def setup(bot):
    await bot.add_cog(PunishmentLoop(bot))
    await bot.add_cog(Management(bot))
