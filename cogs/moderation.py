import datetime

import discord
from discord.ext import commands

import database
from utils import ui
from utils.checks import is_owner


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

    def _log_channel(self, guild):
        ch_id = database.guild_config(guild.id).get("moderation", {}).get("mod_log_channel", 0)
        return guild.get_channel(ch_id)

    async def _mod_log(self, guild, title, description, color=discord.Color.blue()):
        channel = self._log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title=title, description=description, color=color, timestamp=discord.utils.utcnow()
        )
        ui.apply_animated(embed, guild)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    def _is_mod(self, interaction):
        member = interaction.user
        if member.guild_permissions.administrator or member.guild_permissions.ban_members:
            return True
        return member.guild_permissions.manage_messages

    async def _mod_check(self, interaction):
        if self._is_mod(interaction):
            return True
        await interaction.response.send_message(
            embed=ui.alert("error", "Bu komutu kullanma yetkin yok.", interaction=interaction),
            ephemeral=True,
        )
        return False

    @discord.app_commands.command(name="ban", description="Üyeyi sunucudan banlar")
    @discord.app_commands.describe(member="Banlanacak üye", reason="Sebep")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Belirtilmedi"):
        if not await self._mod_check(interaction):
            return
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu üyeyi banlayamazsın.", interaction=interaction),
                ephemeral=True,
            )
            return
        try:
            await member.ban(reason=f"{interaction.user} tarafından: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Yetkim yetmiyor.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Üye Banlandı",
            f"{member.mention} sunucudan banlandı.",
            color="error",
            interaction=interaction,
            timestamp=True,
            emoji_="🔨",
        )
        e.add_field(name="Üye", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=True)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        await ui.animate(interaction, final=e, text="Ban işleniyor", emoji_="🔨", color="error", steps=4, delay=0.15)
        await self._mod_log(interaction.guild, "Ban", f"{member} banlandı.\nSebep: {reason}\nYetkili: {interaction.user.mention}")

    @discord.app_commands.command(name="kick", description="Üyeyi sunucudan atar")
    @discord.app_commands.describe(member="Atılacak üye", reason="Sebep")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Belirtilmedi"):
        if not await self._mod_check(interaction):
            return
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu üyeyi atamazsın.", interaction=interaction),
                ephemeral=True,
            )
            return
        try:
            await member.kick(reason=f"{interaction.user} tarafından: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Yetkim yetmiyor.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Üye Atıldı",
            f"{member.mention} sunucudan atıldı.",
            color="warn",
            interaction=interaction,
            timestamp=True,
            emoji_="👢",
        )
        e.add_field(name="Üye", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=True)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        await ui.animate(interaction, final=e, text="Kick işleniyor", emoji_="👢", color="warn", steps=4, delay=0.15)
        await self._mod_log(interaction.guild, "Kick", f"{member} atıldı.\nSebep: {reason}\nYetkili: {interaction.user.mention}")

    @discord.app_commands.command(name="mute", description="Üyeyi sesli susturur (timeout)")
    @discord.app_commands.describe(member="Susturulacak üye", duration="Dakika cinsinden süre", reason="Sebep")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: int = 60, reason: str = "Belirtilmedi"):
        if not await self._mod_check(interaction):
            return
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu üyeyi susturamazsın.", interaction=interaction),
                ephemeral=True,
            )
            return
        try:
            await member.timeout(datetime.timedelta(minutes=duration), reason=f"{interaction.user} tarafından: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Yetkim yetmiyor.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Üye Susturuldu",
            f"{member.mention} susturuldu.",
            color="warn",
            interaction=interaction,
            timestamp=True,
            emoji_="🤐",
        )
        e.add_field(name="Üye", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Süre", value=f"**{duration}** dakika", inline=True)
        e.add_field(name="Bitiş", value=f"<t:{int((discord.utils.utcnow() + datetime.timedelta(minutes=duration)).timestamp())}:R>", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=False)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        await ui.animate(interaction, final=e, text="Susturma uygulanıyor", emoji_="🤐", color="warn", steps=4, delay=0.15)
        await self._mod_log(interaction.guild, "Mute", f"{member} {duration} dk susturuldu.\nSebep: {reason}\nYetkili: {interaction.user.mention}")

    @discord.app_commands.command(name="unmute", description="Susturmayı kaldırır")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._mod_check(interaction):
            return
        try:
            await member.timeout(None, reason=f"{interaction.user} tarafından kaldırıldı")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Yetkim yetmiyor.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Susturma Kaldırıldı",
            f"{member.mention} artık konuşabilir.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🔊",
        )
        e.add_field(name="Üye", value=member.mention, inline=True)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        await ui.animate(interaction, final=e, text="Susturma kaldırılıyor", emoji_="🔊", color="success", steps=4, delay=0.15)

    @discord.app_commands.command(name="warn", description="Üyeye uyarı verir")
    @discord.app_commands.describe(member="Uyarılacak üye", reason="Sebep")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Belirtilmedi"):
        if not await self._mod_check(interaction):
            return
        warns = await database.get_warns(interaction.guild_id, member.id)
        await database.add_warn(interaction.guild_id, member.id, interaction.user.id, reason)
        total = len(warns) + 1
        e = ui.embed(
            "Uyarı Verildi",
            f"{member.mention} kullanıcısına uyarı verildi.",
            color="warn",
            interaction=interaction,
            timestamp=True,
            emoji_="⚠️",
        )
        e.add_field(name="Üye", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Uyarı No", value=f"**#{total}**", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=False)
        await ui.animate(interaction, final=e, text="Uyarı kaydediliyor", emoji_="⚠️", color="warn", steps=4, delay=0.15)
        await self._mod_log(interaction.guild, "Uyarı", f"{member} uyarıldı.\nSebep: {reason}\nYetkili: {interaction.user.mention}")

    @discord.app_commands.command(name="warnings", description="Üyenin uyarılarını listeler")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._mod_check(interaction):
            return
        warns = await database.get_warns(interaction.guild_id, member.id)
        if not warns:
            await interaction.response.send_message(
                embed=ui.alert("success", f"{member.mention} için uyarı yok. Temiz sicil! ✨", interaction=interaction),
                ephemeral=True,
            )
            return
        lines = []
        for i, (mod_id, reason, created) in enumerate(warns[:10], start=1):
            lines.append(
                f"`{i}.` **{reason}**\n"
                f"🕓 {discord.utils.format_dt(datetime.datetime.fromtimestamp(created, tz=datetime.timezone.utc), style='R')}"
            )
        e = ui.embed(
            f"Uyarılar — {member.display_name}",
            "\n\n".join(lines),
            color="warn",
            interaction=interaction,
            timestamp=True,
            emoji_="📋",
        )
        if len(warns) > 10:
            e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • +{len(warns) - 10} uyarı daha")
        e.set_thumbnail(url=member.display_avatar.url)
        await ui.animate(interaction, final=e, text="Uyarılar getiriliyor", emoji_="📋", color="warn", steps=4, delay=0.15)

    @discord.app_commands.command(name="clearwarns", description="Üyenin uyarılarını temizler")
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._mod_check(interaction):
            return
        await database.clear_warns(interaction.guild_id, member.id)
        e = ui.embed(
            "Uyarılar Temizlendi",
            f"{member.mention} için tüm uyarılar silindi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🧹",
        )
        e.add_field(name="Üye", value=member.mention, inline=True)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        await ui.animate(interaction, final=e, text="Temizleniyor", emoji_="🧹", color="success", steps=4, delay=0.15)

    @discord.app_commands.command(name="purge", description="Belirli sayıda mesajı siler")
    @discord.app_commands.describe(amount="Silinecek mesaj sayısı (maks 100)")
    async def purge(self, interaction: discord.Interaction, amount: int = 50):
        if not await self._mod_check(interaction):
            return
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu komutu kullanma yetkin yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        amount = max(1, min(amount, 100))
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Mesajlar siliniyor",
            emoji_="🗑️",
            color="info",
            detail=f"Hedef: **{amount}** mesaj",
            steps=6,
            delay=0.18,
        )
        deleted = await interaction.channel.purge(limit=amount)
        e = ui.embed(
            "Temizlik Tamamlandı",
            f"{interaction.channel.mention} kanalından mesajlar silindi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🧹",
        )
        e.add_field(name="Silinen Mesaj", value=f"**{len(deleted)}**", inline=True)
        e.add_field(name="Kanal", value=interaction.channel.mention, inline=True)
        e.add_field(name="Yetkili", value=interaction.user.mention, inline=True)
        try:
            await edit(embed=ui.apply_animated(e, interaction.guild), content=None)
        except discord.HTTPException:
            await interaction.followup.send(embed=ui.apply_animated(e, interaction.guild))
        await self._mod_log(interaction.guild, "Temizlik", f"{interaction.channel.mention} içinde {len(deleted)} mesaj silindi.\nYetkili: {interaction.user.mention}")

    @commands.command(name="softban", description="Üyeyi ID ile banlar (softban)")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def softban(self, ctx, user_id: int, *, reason: str = "Belirtilmedi"):
        guild = ctx.guild
        author = ctx.author

        def _check():
            if author.guild_permissions.administrator or author.guild_permissions.ban_members:
                return True
            return False

        if not _check():
            await ctx.send(embed=ui.alert("error", "Bu komutu kullanma yetkin yok."))
            return

        target = guild.get_member(user_id)
        if target is not None and target.top_role >= author.top_role and author.id != guild.owner_id:
            await ctx.send(embed=ui.alert("error", "Bu üyeyi banlayamazsın."))
            return

        try:
            await guild.ban(discord.Object(id=user_id), reason=f"{author} tarafından: {reason}")
        except discord.Forbidden:
            await ctx.send(embed=ui.alert("error", "Yetkim yetmiyor."))
            return
        except discord.HTTPException:
            await ctx.send(embed=ui.alert("error", "Geçersiz üye ID'si veya ban gerçekleştirilemedi."))
            return

        e = ui.embed(
            "Üye Banlandı (Softban)",
            f"`{user_id}` ID'li üye sunucudan banlandı.",
            color="error",
            timestamp=True,
            emoji_="🔨",
        )
        e.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        e.set_footer(text=guild.name)
        e.timestamp = discord.utils.utcnow()
        e.add_field(name="Üye", value=f"`{user_id}`", inline=True)
        e.add_field(name="Sebep", value=f"```{reason}```", inline=True)
        e.add_field(name="Yetkili", value=author.mention, inline=True)
        await ui.animate_message(
            ctx.channel,
            final=e,
            text="Ban işleniyor",
            emoji_="🔨",
            color="error",
            steps=4,
            delay=0.15,
        )
        await self._mod_log(guild, "Softban", f"{user_id} ID'li üye banlandı.\nSebep: {reason}\nYetkili: {author.mention}")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
