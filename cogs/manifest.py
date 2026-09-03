import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui

MANIFEST_CHANNEL_ID = 1537219053523963904

EMOJI_ROLES = [
    (1537227276851216444, 1537218520599887872),
    (1537227055832502372, 1537218497246142474),
    (1537226722636988536, 1537218373811699712),
    (1537225869767221318, 1537218129808330802),
    (1537224930217824286, 1537218834740678756),
    (1537225622139568150, 1537217824437829652),
]

# Telafi sırasında botun kendi tepki silme işlemleri, üyenin seçtiği rolün
# on_raw_reaction_remove yoluyla geri alınmasını tetiklememeli. Bu küme,
# botun bilinçli olarak sildiği (message_id, emoji_id, user_id) kayıtlarını
# tutar; _apply bu kayıtlar için rolü kaldırmaz.
_SUPPRESSED_REMOVALS: set[tuple] = set()


def _resolve_emoji(guild, emoji_id):
    return guild.get_emoji(emoji_id) or discord.PartialEmoji(name="_", id=emoji_id)


class Manifest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="manifestpanel", description="Manifest kızı tepki panelini oluşturur")
    @app_commands.checks.has_permissions(administrator=True)
    async def manifestpanel(self, interaction: discord.Interaction, kanal: discord.TextChannel = None):
        guild = interaction.guild
        channel = kanal or (guild.get_channel(MANIFEST_CHANNEL_ID) if guild else None)
        if channel is None:
            await interaction.response.send_message(
                embed=ui.alert("error", "Kanal bulunamadı.", interaction=interaction),
                ephemeral=True,
            )
            return
        if guild is None:
            await interaction.response.send_message(
                embed=ui.alert("error", "Panel yalnızca sunucu içinde oluşturulabilir.", interaction=interaction),
                ephemeral=True,
            )
            return

        desc = []
        for emoji_id, role_id in EMOJI_ROLES:
            role = guild.get_role(role_id)
            name = role.name if role else f"Rol {role_id}"
            desc.append(f"{_resolve_emoji(guild, emoji_id)} **{name}**")

        embed = ui.embed(
            "Hangi Manifest Kızısın?",
            "Aşağıdaki tepkilerden birine basarak manifest kızı rolünü seç. "
            "İlk seçimin kesindir, sonradan başka birini seçemezsin.\n\n"
            + "\n".join(desc),
            color="pink",
            emoji_="💖",
            timestamp=True,
        )
        embed.set_footer(text=f"{guild.name} • Manifest Kızı")

        await interaction.response.defer(thinking=True, ephemeral=True)
        msg = await channel.send(content="Hangi Manifest Kızısın? @everyone", embed=embed)
        for emoji_id, _role_id in EMOJI_ROLES:
            try:
                await msg.add_reaction(_resolve_emoji(guild, emoji_id))
            except discord.HTTPException:
                pass
        await database.save_manifest_roles(guild.id, msg.id, EMOJI_ROLES)
        await interaction.followup.send(
            embed=ui.alert("success", f"Panel hazır: [Kanala git]({msg.jump_url})", interaction=interaction),
            ephemeral=True,
        )

    @app_commands.command(name="manifesttelafi", description="Bot kapalıyken tepki ekleyenlere rolleri telafi eder")
    @app_commands.checks.has_permissions(administrator=True)
    async def manifesttelafi(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        granted, skipped = await self._catch_up_reactions()
        e = ui.alert(
            "success" if granted else "info",
            f"Telafi tamamlandı: **{granted}** kişiye rol verildi, **{skipped}** tepki atlandı.",
            interaction=interaction,
        )
        await interaction.followup.send(embed=e, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        await asyncio.sleep(5)
        try:
            granted, skipped = await self._catch_up_reactions()
            if granted or skipped:
                print(f"[Manifest] Çevrimdışı telafi: {granted} rol verildi, {skipped} atlandı")
        except Exception:
            pass

    async def _catch_up_reactions(self):
        channel = self.bot.get_channel(MANIFEST_CHANNEL_ID)
        if channel is None:
            return 0, 0
        guild = channel.guild
        rows = await database.get_guild_manifest_roles(guild.id)
        if not rows:
            return 0, 0
        panels = {}
        for r in rows:
            panels.setdefault(r["message_id"], []).append(r)
        granted = skipped = 0
        async for message in channel.history(limit=None, oldest_first=True):
            panel_rows = panels.get(message.id)
            if not panel_rows:
                continue
            emoji_to_role = {r["emoji_id"]: r["role_id"] for r in panel_rows}
            rank = {e: i for i, e in enumerate(emoji_to_role)}
            reactions = [
                reac
                for reac in message.reactions
                if getattr(reac.emoji, "id", None) in emoji_to_role
            ]
            if not reactions:
                continue
            votes = {}
            for reac in reactions:
                try:
                    users = [u async for u in reac.users(limit=None)]
                except discord.HTTPException:
                    continue
                for user in users:
                    if user.id == self.bot.user.id:
                        continue
                    votes.setdefault(user.id, []).append(reac)
            for user_id, reacted in votes.items():
                member = guild.get_member(user_id)
                if member is None:
                    continue
                reacted.sort(key=lambda reac: rank[reac.emoji.id])
                current = [
                    r
                    for rid in emoji_to_role.values()
                    for r in (guild.get_role(rid),)
                    if r is not None and r in member.roles
                ]
                if current:
                    skipped += 1
                    for reac in reacted:
                        await self._remove_reaction_quietly(message, reac.emoji, member)
                    continue
                target = guild.get_role(emoji_to_role[reacted[0].emoji.id])
                if target is not None:
                    try:
                        await member.add_roles(target, reason="[Manifest] Çevrimdışı dönem telafisi")
                        granted += 1
                    except discord.HTTPException:
                        pass
                for reac in reacted[1:]:
                    await self._remove_reaction_quietly(message, reac.emoji, member)
        return granted, skipped

    async def _remove_reaction_quietly(self, message, emoji, member):
        """Telafi sırasında tepkiyi siler; bu silmenin _apply'e
        'rolü kaldır' olarak yansımamasını sağlar."""
        _SUPPRESSED_REMOVALS.add((message.id, emoji.id, member.id))
        try:
            await message.remove_reaction(emoji, member)
        except discord.HTTPException:
            pass

    async def _apply(self, payload, adding):
        if payload.user_id == self.bot.user.id:
            return
        rows = await database.get_manifest_roles(payload.message_id)
        if not rows:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if payload.emoji.id is None:
            return
        if not adding and (payload.message_id, payload.emoji.id, payload.user_id) in _SUPPRESSED_REMOVALS:
            _SUPPRESSED_REMOVALS.discard((payload.message_id, payload.emoji.id, payload.user_id))
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            return
        for row in rows:
            if row["emoji_id"] != payload.emoji.id:
                continue
            role = guild.get_role(row["role_id"])
            if role is None:
                return
            try:
                if adding:
                    current = [
                        r
                        for r in (guild.get_role(rr["role_id"]) for rr in rows)
                        if r is not None and r is not role and r in member.roles
                    ]
                    if current:
                        if role in member.roles:
                            await member.remove_roles(role, reason="[Manifest] Tek rol seçimi")
                        try:
                            channel = guild.get_channel(payload.channel_id)
                            if channel is not None:
                                msg = await channel.fetch_message(payload.message_id)
                                await msg.remove_reaction(payload.emoji, member)
                        except discord.HTTPException:
                            pass
                        return
                    if role not in member.roles:
                        await member.add_roles(role, reason="[Manifest] Tepki ile rol verildi")
                else:
                    if role in member.roles:
                        await member.remove_roles(role, reason="[Manifest] Tepki kaldırıldı")
            except discord.HTTPException:
                pass
            return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._apply(payload, adding=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._apply(payload, adding=False)


async def setup(bot):
    await bot.add_cog(Manifest(bot))
