import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui


def _norm_emoji(emoji: str) -> str:
    return emoji.replace("\uFE0F", "").strip()


class GenderVerify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _cfg(self, guild_id):
        return database.guild_config(guild_id).get("gender_roles", {})

    async def _cleanup_channel(self, channel, keep=1):
        try:
            messages = [msg async for msg in channel.history(limit=100)]
        except (discord.HTTPException, discord.Forbidden):
            return
        bot_messages = [m for m in messages if m.author == self.bot.user]
        if len(bot_messages) <= keep:
            return
        to_delete = bot_messages[keep:]
        for msg in to_delete:
            try:
                await msg.delete(reason="[Cinsiyet] Eski seçim mesajı temizlendi")
            except (discord.HTTPException, discord.NotFound):
                pass

    async def _send_welcome(self, member):
        cfg = self._cfg(member.guild.id)
        if not cfg.get("enabled", True):
            return
        channel = member.guild.get_channel(cfg.get("channel_id", 0))
        if channel is None:
            return
        male_role = member.guild.get_role(cfg.get("male_role_id", 0))
        female_role = member.guild.get_role(cfg.get("female_role_id", 0))
        if male_role is None or female_role is None:
            return
        male_emoji = cfg.get("male_emoji") or "♂️"
        female_emoji = cfg.get("female_emoji") or "♀️"

        embed = ui.embed(
            "Cinsiyet Seçimi",
            f"Hoş geldin {member.mention}! 🎉\n\n"
            f"Cinsiyet rolünü almak için aşağıdaki tepkilerden birine tıkla:\n"
            f"{male_emoji} **Erkek** → `{male_role.name}`\n"
            f"{female_emoji} **Kız** → `{female_role.name}`",
            color="teal",
            emoji_="👤",
            timestamp=True,
        )
        embed.set_footer(text=f"{member.guild.name} • Cinsiyet Seçimi")
        msg = await channel.send(embed=embed)
        try:
            await msg.add_reaction(male_emoji)
            await msg.add_reaction(female_emoji)
        except discord.HTTPException:
            pass
        await database.save_gender_verify(member.guild.id, channel.id, msg.id, member.id)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.guild or member.bot:
            return
        if member.pending:
            return
        try:
            await self._send_welcome(member)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not after.guild or before.bot or after.bot:
            return
        if before.pending and not after.pending:
            try:
                await self._send_welcome(after)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        row = await database.get_gender_verify(payload.message_id)
        if row is None:
            print(f"[Gender] Tepki algılandi ama DB'de kayit yok: msg={payload.message_id}")
            return
        if row["user_id"] != payload.user_id:
            print(f"[Gender] Tepkiyi baska biri atti: beklenen={row['user_id']}, atan={payload.user_id}")
            return
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        cfg = self._cfg(guild.id)
        if not cfg.get("enabled", True):
            return
        male_emoji = _norm_emoji(cfg.get("male_emoji") or "♂️")
        female_emoji = _norm_emoji(cfg.get("female_emoji") or "♀️")
        reacted = _norm_emoji(str(payload.emoji))
        if reacted not in (male_emoji, female_emoji):
            return

        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return

        male_role = guild.get_role(cfg.get("male_role_id", 0))
        female_role = guild.get_role(cfg.get("female_role_id", 0))
        if male_role is None or female_role is None:
            print(f"[Gender] Roller bulunamadi: male={male_role}, female={female_role}")
            return

        if reacted == male_emoji:
            target, other = male_role, female_role
        else:
            target, other = female_role, male_role

        try:
            if other in member.roles:
                await member.remove_roles(other, reason="[Cinsiyet] Diger cinsiyet rolü kaldirildi")
            if target not in member.roles:
                await member.add_roles(target, reason="[Cinsiyet] Tepki ile cinsiyet rolü verildi")
            print(f"[Gender] {member} - {target.name} rolu verildi")
        except discord.HTTPException as e:
            print(f"[Gender] Rol verilemedi: {e}")

        await database.delete_gender_verify(payload.message_id)

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except discord.HTTPException:
                return
        try:
            msg = await channel.fetch_message(payload.message_id)
            await msg.delete()
            print(f"[Gender] Mesaj silindi: {payload.message_id}")
        except (discord.HTTPException, discord.NotFound):
            print(f"[Gender] Mesaj silinemedi: {payload.message_id}")

        await self._cleanup_channel(channel, keep=1)

    @app_commands.command(name="kanaltemizle", description="Cinsiyet kanalındaki eski mesajları temizler (en yeni mesaj hariç)")
    @app_commands.checks.has_permissions(administrator=True)
    async def temizle(self, interaction: discord.Interaction):
        cfg = self._cfg(interaction.guild_id)
        channel_id = cfg.get("channel_id", 0)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            await interaction.response.send_message("Cinsiyet kanalı bulunamadı.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await self._cleanup_channel(channel, keep=1)
        await interaction.followup.send(f"{channel.mention} kanalındaki eski mesajlar temizlendi.")


async def setup(bot):
    await bot.add_cog(GenderVerify(bot))
