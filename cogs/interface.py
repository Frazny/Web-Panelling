import discord
from discord.ext import commands

from utils import ui

CATEGORY_EMOJIS = {
    "cogs.guard": "🛡️",
    "cogs.moderation": "⚙️",
    "cogs.registration": "📋",
    "cogs.levels": "⭐",
    "cogs.invites": "📨",
    "cogs.tickets": "🎫",
    "cogs.interface": "ℹ️",
    "cogs.music": "🎵",
    "cogs.economy": "💰",
    "cogs.logging": "📝",
    "cogs.utility": "🎲",
    "cogs.rolemenu": "🎨",
    "cogs.social": "📣",
    "cogs.management": "🔧",
    "cogs.automod": "🤖",
}

CATEGORY_NAMES = {
    "cogs.guard": "Guard",
    "cogs.moderation": "Moderasyon",
    "cogs.registration": "Kayıt",
    "cogs.levels": "Seviye",
    "cogs.invites": "Davet",
    "cogs.tickets": "Ticket",
    "cogs.interface": "Arayüz",
    "cogs.music": "Müzik",
    "cogs.economy": "Ekonomi",
    "cogs.logging": "Loglama",
    "cogs.utility": "Eğlence & Araçlar",
    "cogs.rolemenu": "Reaksiyon Rolleri",
    "cogs.social": "Sosyal",
    "cogs.management": "Yönetim",
    "cogs.automod": "AutoMod",
}


class Interface(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _build_commands_embed(self, interaction=None):
        grouped = {}
        for cmd in self.bot.tree.get_commands():
            module = getattr(cmd, "module", "") or ""
            grouped.setdefault(module, []).append(cmd)

        total = sum(len(cmds) for cmds in grouped.values())
        embed = ui.embed(
            "Komutlar",
            f"Aşağıda botun tüm komutları kategorilere göre listelenmiştir.\nKomutları kullanmak için Discord'a `/` yaz ve listeden seç.",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="📜",
        )
        for module, cmds in sorted(grouped.items(), key=lambda x: CATEGORY_NAMES.get(x[0], x[0])):
            if module == "cogs.interface":
                continue
            emoji = CATEGORY_EMOJIS.get(module, "📌")
            name = CATEGORY_NAMES.get(module, module.replace("cogs.", "").title())
            lines = []
            for c in cmds:
                if getattr(c, "commands", None):
                    subs = [s.name for s in c.commands]
                    lines.append(f"**/{c.name}** *({', '.join(subs)})* — {c.description}")
                else:
                    lines.append(f"**/{c.name}** — {c.description}")
            embed.add_field(
                name=f"{emoji} {name}",
                value="\n".join(lines) or "Yok",
                inline=False,
            )
        embed.add_field(name="ℹ️ Genel", value=f"**{total}** komut • **{len(self.bot.cogs)}** sistem", inline=False)
        embed.set_footer(text="Prefix komutu olarak: !komutlar")
        return embed

    @commands.command(name="komutlar", description="Tüm komutları listeler")
    async def komutlar_prefix(self, ctx):
        await ctx.send(embed=self._build_commands_embed())

    @discord.app_commands.command(name="komutlar", description="Tüm komutları listeler")
    async def komutlar_slash(self, interaction: discord.Interaction):
        await ui.animate(
            interaction,
            final=self._build_commands_embed(interaction),
            text="Komutlar derleniyor",
            emoji_="📜",
            color="info",
            steps=4,
            delay=0.14,
        )


async def setup(bot):
    await bot.add_cog(Interface(bot))
