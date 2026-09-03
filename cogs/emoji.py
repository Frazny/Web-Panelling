import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils import emoji_anim, ui

PREFIX = "anim_"


class Emojis(commands.Cog):
    """Animasyonlu emoji paketini sunucuya yükler ve yönetir."""

    def __init__(self, bot):
        self.bot = bot

    def _can_manage(self, guild):
        return guild.me.guild_permissions.manage_expressions

    def _packed(self, guild):
        return [e for e in guild.emojis if e.name.startswith(PREFIX)]

    @app_commands.command(
        name="emojiler",
        description="Animasyonlu emoji paketini yükler veya yönetir",
    )
    @app_commands.default_permissions(manage_expressions=True)
    @app_commands.rename(secim="islem")
    @app_commands.choices(
        secim=[
            app_commands.Choice(name="📥 Paketi yükle", value="kur"),
            app_commands.Choice(name="🗑️ Paketi temizle", value="temizle"),
            app_commands.Choice(name="📋 Paketi listele", value="liste"),
        ]
    )
    async def emojiler(self, interaction: discord.Interaction, secim: str):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Bu komut bir sunucuda kullanılmalı.", ephemeral=True
            )
        if not self._can_manage(guild):
            e = ui.alert(
                "error",
                "Botun `Emoji ve Çıkartmaları Yönet` (Manage Expressions) izni yok.\n"
                "Sunucu Ayarları → Roller → bot rolü → `Emoji ve Çıkartmaları Yönet`'i açın.",
                interaction=interaction,
            )
            return await interaction.response.send_message(embed=e, ephemeral=True)

        if secim == "kur":
            await self._kur(interaction)
        elif secim == "temizle":
            await self._temizle(interaction)
        else:
            await self._liste(interaction)

    async def _kur(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer(thinking=True, ephemeral=True)
        edit = interaction.edit_original_response

        progress = discord.Embed(
            title="📥 Emoji paketi hazırlanıyor",
            description="GIF'ler üretiliyor…",
            color=ui.color("info"),
        )
        await edit(embed=progress)

        try:
            pack = await asyncio.to_thread(emoji_anim.build_pack)
        except Exception:
            pack = []

        total = len(pack)
        if not total:
            e = ui.alert("error", "Emoji paketi üretilemedi.", interaction=interaction)
            return await edit(embed=e)

        ok, fail = [], []
        for i, item in enumerate(pack, start=1):
            try:
                emoji = await guild.create_custom_emoji(
                    name=item["name"],
                    image=item["data"],
                    reason="Animasyonlu emoji paketi",
                )
                ok.append(emoji)
            except discord.HTTPException as exc:
                fail.append((item["name"], exc))
            # Emoji oluşturma rate limit'ine (10/10sn) takılmamak için ara ara bekle
            if i % 3 == 0:
                await asyncio.sleep(1.2)
            desc = f"`{ui.bar(i, total, width=16)}` **{i}/{total}**\n"
            desc += "\n".join(
                [f"✅ <:{e.name}:{e.id}>" for e in ok[-5:]]
            )
            await edit(
                embed=discord.Embed(
                    title=f"📥 Yükleniyor… ({i}/{total})",
                    description=desc or "…",
                    color=ui.color("info"),
                )
            )

        lines = [f"{emoji} **:{emoji.name}:** — `:{emoji.name}:`" for emoji in ok]
        e = ui.embed(
            "Paket yüklendi",
            "Sunucuya animasyonlu emojiler eklendi. Mesajlarında `:emoji_adı:` şeklinde kullan.",
            color="success",
            interaction=interaction,
            emoji_="✅",
        )
        for chunk_start in range(0, len(lines), 5):
            e.add_field(name="Eklenenler", value="\n".join(lines[chunk_start : chunk_start + 5]), inline=False)
        if fail:
            e.add_field(
                name="Eklenemeyenler",
                value="\n".join(f"`{n}` — {type(ex).__name__}" for n, ex in fail),
                inline=False,
            )
        await edit(embed=e)

    async def _temizle(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.defer(thinking=True, ephemeral=True)
        edit = interaction.edit_original_response

        existing = self._packed(guild)
        if not existing:
            e = ui.alert("info", "Silinecek paket emojisi bulunamadı.", interaction=interaction)
            return await edit(embed=e)

        total = len(existing)
        for i, emoji in enumerate(existing, start=1):
            try:
                await emoji.delete(reason="Animasyonlu emoji paketi temizliği")
            except discord.HTTPException:
                pass
            await edit(
                embed=discord.Embed(
                    title="🗑️ Temizleniyor…",
                    description=f"`{ui.bar(i, total, width=16)}` **{i}/{total}**",
                    color=ui.color("warn"),
                )
            )
        e = ui.embed(
            "Paket temizlendi",
            f"**{total}** animasyonlu emoji sunucudan kaldırıldı.",
            color="success",
            interaction=interaction,
            emoji_="🗑️",
        )
        await edit(embed=e)

    async def _liste(self, interaction: discord.Interaction):
        existing = self._packed(interaction.guild)
        e = ui.embed(
            "Animasyonlu emojiler",
            "Sunucudaki paket emojileri:",
            color="info",
            interaction=interaction,
            emoji_="📋",
        )
        if not existing:
            e.add_field(name="Sonuç", value="Henüz yüklenmiş paket emojisi yok. `/emojiler` → `Paketi yükle`.")
        else:
            lines = [f"{emoji} `:{emoji.name}:`" for emoji in existing]
            for start in range(0, len(lines), 6):
                e.add_field(name="Emojiler", value="\n".join(lines[start : start + 6]), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Emojis(bot))
