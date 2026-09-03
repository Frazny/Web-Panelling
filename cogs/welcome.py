import asyncio
import io

import discord
from discord.ext import commands

from utils import animations


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _cfg(self, guild_id):
        import database
        return database.guild_config(guild_id).get("welcome", {})

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        if member.pending:
            return
        await self._welcome(member)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.bot or after.bot:
            return
        if before.pending and not after.pending:
            await self._welcome(after)

    async def _welcome(self, member):
        cfg = self._cfg(member.guild.id)
        if not cfg.get("enabled", True):
            return
        channel = member.guild.get_channel(cfg.get("channel_id", 0))
        if channel is None:
            return
        auto_role = member.guild.get_role(cfg.get("auto_role_id", 0))
        if auto_role is not None and auto_role not in member.roles:
            try:
                await member.add_roles(auto_role, reason="Hoş geldin otomatik rolü")
            except discord.Forbidden:
                pass
        try:
            async with channel.typing():
                avatar = await member.display_avatar.read()
                gif = await asyncio.to_thread(
                    animations.create_welcome_gif,
                    avatar,
                    member.display_name,
                    member.guild.member_count,
                )
            await channel.send(file=discord.File(io.BytesIO(gif), filename="hosgeldin.gif"))
            return
        except Exception:
            pass
        message = cfg.get("message", "Hoş geldin {user}! Üye sayısı: {count}").format(
            user=member.mention, count=member.guild.member_count
        )
        try:
            await channel.send(message)
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(Welcome(bot))
