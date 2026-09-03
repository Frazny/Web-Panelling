import asyncio

import discord
from discord.ext import commands

import database
from utils import ui


class TicketButton(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ticket Aç", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = database.guild_config(interaction.guild_id).get("tickets", {})
        if not cfg.get("enabled", True):
            await interaction.response.send_message(
                embed=ui.alert("error", "Ticket sistemi kapalı.", interaction=interaction),
                ephemeral=True,
            )
            return
        guild = interaction.guild
        existing_id = await database.get_user_open_ticket(guild.id, interaction.user.id)
        if existing_id:
            existing = guild.get_channel(existing_id)
            if existing is not None:
                await interaction.response.send_message(
                    embed=ui.alert(
                        "warn",
                        f"Zaten açık bir ticket'ın var: {existing.mention}.\nTicket kapandıktan sonra yeni bir tane açabilirsin.",
                        interaction=interaction,
                    ),
                    ephemeral=True,
                )
                return
            # Eski ticket kanalı elle silinmiş: bayat kaydı kapat, yeniden açılmasına izin ver
            await database.close_ticket(guild.id, existing_id)
        category = guild.get_channel(cfg.get("category_id", 0))
        support_role = guild.get_role(cfg.get("support_role_id", 0))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True)
        clean = "".join(c.lower() for c in interaction.user.display_name if c.isalnum())
        clean = clean[:20] or "user"
        name = f"ticket-{clean}"
        try:
            channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=ui.alert("error", "Kanal oluşturma yetkim yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        await database.create_ticket(guild.id, channel.id, interaction.user.id)
        embed = ui.embed(
            "Yeni Ticket",
            f"{interaction.user.mention} tarafından açıldı. Destek ekibi en kısa sürede ilgilenecek.",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🎫",
        )
        embed.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Ticket # {channel.id % 100000}")
        await channel.send(embed=embed, view=CloseTicketView())
        await interaction.response.send_message(
            embed=ui.alert("success", f"Ticket açıldı: {channel.mention}", interaction=interaction),
            ephemeral=True,
        )


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket Kapat", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await database.close_ticket(interaction.guild_id, interaction.channel_id)
        try:
            await interaction.channel.send("🕐 Ticket **5 saniye** içinde kapatılıyor…")
            await asyncio.sleep(5)
            await interaction.channel.delete()
        except discord.Forbidden:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _cfg(self, guild_id):
        return database.guild_config(guild_id).get("tickets", {})

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketButton(self.bot))
        self.bot.add_view(CloseTicketView())
        print("[Ticket] Ticket sistemi hazır.")

    @discord.app_commands.command(name="ticketpanel", description="Ticket açma panelini kanala gönderir")
    async def ticketpanel(self, interaction: discord.Interaction):
        cfg = self._cfg(interaction.guild_id)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=ui.alert("error", "Yetkin yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(cfg.get("channel_id", 0)) or interaction.channel
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Panel oluşturuluyor",
            emoji_="🎫",
            color="info",
            steps=4,
            delay=0.15,
        )
        embed = ui.embed(
            "Destek Talebi",
            "Aşağıdaki butona tıklayarak destek talebi açabilirsin.\n\nBir yetkili en kısa sürede seninle ilgilenecektir.",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🎫",
        )
        embed.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Destek Paneli")
        await channel.send(embed=embed, view=TicketButton(self.bot))
        result = ui.embed(
            "Panel Gönderildi",
            f"Ticket paneli **{channel.mention}** kanalına iletildi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="✅",
        )
        result.add_field(name="Kanal", value=channel.mention, inline=True)
        await edit(embed=ui.apply_animated(result, interaction.guild), content=None)

    @discord.app_commands.command(name="ticketclose", description="Aktif ticket kanalını kapatır")
    async def ticketclose(self, interaction: discord.Interaction):
        cfg = self._cfg(interaction.guild_id)
        support_role = interaction.guild.get_role(cfg.get("support_role_id", 0))
        is_support = (
            interaction.user.guild_permissions.administrator
            or (support_role is not None and support_role in interaction.user.roles)
        )
        if not is_support and not interaction.channel.name.startswith("ticket-"):
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu komutu burada kullanamazsın.", interaction=interaction),
                ephemeral=True,
            )
            return
        await ui.animate(
            interaction,
            defer=True,
            text="Ticket kapatılıyor",
            emoji_="🔒",
            color="error",
            steps=4,
            delay=0.2,
        )
        await database.close_ticket(interaction.guild_id, interaction.channel_id)
        await asyncio.sleep(2)
        try:
            await interaction.channel.delete()
        except discord.Forbidden:
            pass


async def setup(bot):
    await bot.add_cog(Tickets(bot))
