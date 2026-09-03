import json

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui


def _role_name(guild, role_id):
    role = guild.get_role(role_id)
    return role.name if role else f"Rol {role_id}"


class RoleButton(discord.ui.Button):
    def __init__(self, role_id, emoji=None, label=None):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label or f"Rol {role_id}",
            emoji=emoji,
            custom_id=f"rolemenu:{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ Rol bulunamadı.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ **{role.name}** rolünü aldım.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ **{role.name}** rolü verildi!", ephemeral=True)


class RoleMenuView(discord.ui.View):
    def __init__(self, items):
        super().__init__(timeout=None)
        for item in items:
            self.add_item(RoleButton(item["role"], emoji=item.get("emoji"), label=item.get("label")))


class RoleMenu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rolpanel", description="Butonlu rol paneli oluşturur")
    @app_commands.checks.has_permissions(administrator=True)
    async def rolpanel(self, interaction: discord.Interaction, kanal: discord.TextChannel, başlık: str = "Rol Menüsü"):
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Panel oluşturuluyor",
            emoji_="🎨",
            color="pink",
            detail=kanal.mention,
            steps=5,
            delay=0.18,
        )
        embed = ui.embed(
            başlık[:256],
            "Aşağıdaki butonlara tıklayarak rol alabilir veya bırakabilirsin.",
            color="pink",
            interaction=interaction,
            timestamp=True,
            emoji_="🎨",
        )
        embed.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Rol Paneli")
        view = RoleMenuView([])
        msg = await kanal.send(embed=embed, view=view)
        await database.save_role_menu(interaction.guild_id, msg.id, kanal.id, {"title": başlık, "items": []})
        result = ui.embed(
            "Panel Oluşturuldu",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="✅",
        )
        result.add_field(name="Bağlantı", value=f"[Panele git]({msg.jump_url})", inline=True)
        result.add_field(name="Sonraki Adım", value="`/rolekle` ile rol ekle", inline=True)
        await edit(embed=ui.apply_animated(result, interaction.guild), content=None)

    @app_commands.command(name="rolekle", description="Rol paneline rol ekler")
    @app_commands.checks.has_permissions(administrator=True)
    async def rolekle(self, interaction: discord.Interaction, panel: str, rol: discord.Role, emoji: str | None = None, etiket: str | None = None):
        menus = await database.get_role_menus(interaction.guild_id)
        target = next((m for m in menus if str(m["message_id"]) == panel or str(m["payload"].get("title", "")) == panel), None)
        if not target:
            titles = "\n".join(f"`{m['message_id']}` — {m['payload'].get('title', '')}" for m in menus[:10])
            await interaction.response.send_message(
                embed=ui.alert("error", f"Panel bulunamadı. Mevcut paneller:\n{titles}", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Rol ekleniyor",
            emoji_="🎨",
            color="pink",
            detail=rol.name,
            steps=5,
            delay=0.16,
        )
        payload = target["payload"]
        payload.setdefault("items", []).append({"role": rol.id, "emoji": emoji, "label": etiket})
        await database.save_role_menu(interaction.guild_id, target["message_id"], target["channel_id"], payload)

        channel = interaction.guild.get_channel(target["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(target["message_id"])
            except discord.HTTPException:
                msg = None
            if msg:
                embed = msg.embeds[0] if msg.embeds else discord.Embed(title="Rol Menüsü")
                embed.description = "\n".join(
                    f"{it.get('emoji', '🎟️')} {it.get('label') or _role_name(interaction.guild, it['role'])}"
                    for it in payload["items"]
                ) or "Aşağıdaki butonlara tıklayarak rol alabilirsin."
                await msg.edit(embed=ui.apply_animated(embed, interaction.guild), view=RoleMenuView(payload["items"]))
        result = ui.embed(
            "Rol Eklendi",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🎨",
        )
        result.add_field(name="Rol", value=rol.mention, inline=True)
        result.add_field(name="Etiket", value=etiket or rol.name, inline=True)
        result.add_field(name="Kalan Buton", value=f"{len(payload['items'])}/25", inline=True)
        await edit(embed=ui.apply_animated(result, interaction.guild), content=None)


async def setup(bot):
    await bot.add_cog(RoleMenu(bot))
