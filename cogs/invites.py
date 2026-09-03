import discord
from discord.ext import commands

import database
from utils import ui


class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invites = {}

    async def _cache_invites(self, guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return
        self.invites[guild.id] = {inv.code: inv.uses for inv in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)
        print("[Davet] Davet takibi hazır.")

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        self.invites.setdefault(invite.guild.id, {})[invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        self.invites.setdefault(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        before = self.invites.get(guild.id, {})
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return
        after = {inv.code: inv.uses for inv in invites}
        self.invites[guild.id] = after
        for code, uses in after.items():
            if uses > before.get(code, 0):
                for inv in invites:
                    if inv.code == code and inv.inviter:
                        await database.add_invite_use(guild.id, inv.inviter.id, member.id)
                        return

    @discord.app_commands.command(name="invites", description="Davet sayını görüntüle")
    @discord.app_commands.describe(member="Bakılacak üye (boş bırakılırsa kendin)")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        uses = await database.get_invite_uses(interaction.guild_id, member.id)
        e = ui.embed(
            "Davet İstatistikleri",
            description=None,
            color="teal",
            interaction=interaction,
            timestamp=True,
            emoji_="📨",
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Üye", value=member.mention, inline=True)
        e.add_field(name="Toplam Davet", value=f"**{uses}** 📨", inline=True)
        e.add_field(name="Durum", value="🌟 Yıldız Davetçi" if uses >= 20 else "💪 Aktif Davetçi" if uses >= 10 else "🌱 Yeni Davetçi", inline=True)
        e.add_field(name="İlerleme", value=f"`{ui.bar(uses, 20, width=16)}`", inline=False)
        await ui.animate(interaction, final=e, text="Davetler hesaplanıyor", emoji_="📨", color="teal", steps=4, delay=0.14)

    @discord.app_commands.command(name="topinvites", description="En çok davet yapanlar")
    async def topinvites(self, interaction: discord.Interaction):
        rows = await database.get_invite_leaderboard(interaction.guild_id, 10)
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        max_uses = max((uses for _, uses in rows), default=1)
        for i, (user_id, uses) in enumerate(rows):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"Bilinmeyen ({user_id})"
            mark = medals[i] if i < 3 else f"`{i+1}.`"
            lines.append(f"{mark} {name} — **{uses}** davet\n{ui.bar(uses, max_uses, width=12)}")
        if not lines:
            await interaction.response.send_message(
                embed=ui.alert("error", "Henüz veri yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "En Çok Davet Yapanlar",
            "\n\n".join(lines),
            color="teal",
            interaction=interaction,
            timestamp=True,
            emoji_="🏆",
        )
        await ui.animate(interaction, final=e, text="Sıralama yükleniyor", emoji_="🏆", color="teal", steps=4, delay=0.15)


async def setup(bot):
    await bot.add_cog(Invites(bot))
