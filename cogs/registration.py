import discord
from discord.ext import commands

import database
from utils import ui
from utils.checks import has_role, is_owner


class Registration(commands.Cog):
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

    def _cfg(self, guild_id):
        return database.guild_config(guild_id).get("registration", {})

    @discord.app_commands.command(name="kayit", description="Üyeyi kayıt eder ve rolü verir")
    @discord.app_commands.describe(member="Kayıt edilecek üye")
    async def kayit(self, interaction: discord.Interaction, member: discord.Member):
        cfg = self._cfg(interaction.guild_id)
        if not cfg.get("enabled", True):
            await interaction.response.send_message(
                embed=ui.alert("error", "Kayıt sistemi kapalı.", interaction=interaction),
                ephemeral=True,
            )
            return
        staff_role = cfg.get("staff_role_id", 0)
        if not has_role(interaction.user, staff_role) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu komutu kullanma yetkin yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        registered_role = interaction.guild.get_role(cfg.get("registered_role_id", 0))
        if registered_role is None:
            await interaction.response.send_message(
                embed=ui.alert("error", "config.json içinde registered_role_id ayarlanmamış.", interaction=interaction),
                ephemeral=True,
            )
            return
        if registered_role in member.roles:
            await interaction.response.send_message(
                embed=ui.alert("warn", f"{member.mention} zaten kayıtlı.", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Kayıt işleniyor",
            emoji_="📋",
            color="teal",
            detail=member.mention,
            steps=5,
            delay=0.18,
        )
        await member.add_roles(registered_role, reason=f"Kayıt eden: {interaction.user}")
        e = ui.embed(
            "Kayıt Tamamlandı",
            f"{member.mention} başarıyla kayıt edildi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="📋",
        )
        e.add_field(name="Üye", value=member.mention, inline=True)
        e.add_field(name="Verilen Rol", value=registered_role.mention, inline=True)
        e.add_field(name="Kayıt Eden", value=interaction.user.mention, inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @discord.app_commands.command(name="kayitsiz", description="Üyenin kayıt rolünü alır")
    @discord.app_commands.describe(member="Rolü alınacak üye")
    async def kayitsiz(self, interaction: discord.Interaction, member: discord.Member):
        cfg = self._cfg(interaction.guild_id)
        staff_role = cfg.get("staff_role_id", 0)
        if not has_role(interaction.user, staff_role) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu komutu kullanma yetkin yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        registered_role = interaction.guild.get_role(cfg.get("registered_role_id", 0))
        if registered_role is not None and registered_role in member.roles:
            edit = await ui.animate(
                interaction,
                defer=True,
                text="Kayıt iptal ediliyor",
                emoji_="📋",
                color="warn",
                detail=member.mention,
                steps=4,
                delay=0.16,
            )
            await member.remove_roles(registered_role, reason=f"İptal eden: {interaction.user}")
            e = ui.embed(
                "Kayıt İptal Edildi",
                f"{member.mention} kaydı iptal edildi.",
                color="warn",
                interaction=interaction,
                timestamp=True,
                emoji_="📋",
            )
            e.add_field(name="Üye", value=member.mention, inline=True)
            e.add_field(name="Alınan Rol", value=registered_role.mention, inline=True)
            await edit(embed=ui.apply_animated(e, interaction.guild), content=None)
        else:
            await interaction.response.send_message(
                embed=ui.alert("warn", f"{member.mention} kayıtlı değil.", interaction=interaction),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Registration(bot))
