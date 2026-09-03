import asyncio
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui


class GiveawayLoop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    async def cog_load(self):
        self.task = asyncio.create_task(self._loop())

    async def cog_unload(self):
        if self.task:
            self.task.cancel()

    async def _loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    for gid, message_id, chid, end_at, winners, prize in await database.get_active_giveaways(guild.id):
                        if end_at > int(time.time()):
                            continue
                        channel = self.bot.get_channel(chid)
                        if channel:
                            try:
                                msg = await channel.fetch_message(message_id)
                                users = [u for u in await msg.reactions[0].users().flatten() if not u.bot] if msg.reactions else []
                            except discord.HTTPException:
                                users = []
                            picked = random.sample(users, min(winners, len(users))) if users else []
                            if picked:
                                await channel.send(
                                    f"🎉 **Çekiliş sonuçlandı!** Ödül: **{prize}**\n"
                                    f"Kazananlar: {', '.join(u.mention for u in picked)}"
                                )
                            else:
                                await channel.send(f"🎉 **Çekiliş sonuçlandı!** Ödül: **{prize}**\nKatılımcı olmadığı için kazanan yok.")
                        await database.mark_giveaway_done(gid)
            except Exception:
                pass
            await asyncio.sleep(10)


class Social(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="anket", description="Butonlu anket oluşturur")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def anket(self, interaction: discord.Interaction, soru: str):
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.success, emoji="✅", custom_id="anket:evet"))
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.danger, emoji="❌", custom_id="anket:hayir"))
        e = ui.embed(
            "Anket",
            soru,
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="📊",
        )
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Katılmak için butonlara bas")
        await interaction.response.send_message(embed=e, view=view)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if interaction.data.get("custom_id") not in ("anket:evet", "anket:hayir"):
            return
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.HTTPException:
                pass

    @app_commands.command(name="cekilis", description="Çekiliş başlatır")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def cekilis(self, interaction: discord.Interaction, ödül: str, süre: str, kazanan: app_commands.Range[int, 1, 10] = 1):
        units = {"s": 1, "d": 86400, "sa": 3600, "dk": 60, "g": 86400}
        try:
            amount = int("".join(c for c in süre if c.isdigit()))
            unit = "".join(c for c in süre if not c.isdigit()).lower()
            seconds = amount * units.get(unit, 60)
        except Exception:
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz süre. Örn: `30dk`, `2sa`, `1g`", interaction=interaction),
                ephemeral=True,
            )
            return
        if seconds < 10 or seconds > 2592000:
            await interaction.response.send_message(
                embed=ui.alert("error", "Süre 10 saniye ile 30 gün arasında olmalı.", interaction=interaction),
                ephemeral=True,
            )
            return
        end = int(time.time()) + seconds
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Çekiliş kuruluyor",
            emoji_="🎉",
            color="pink",
            detail=ödül[:100],
            steps=5,
            delay=0.18,
        )
        e = ui.embed(
            f"Çekiliş: {ödül[:256]}",
            description=None,
            color="pink",
            interaction=interaction,
            timestamp=True,
            emoji_="🎉",
        )
        e.add_field(name="Ödül", value=f"**{ödül}**", inline=True)
        e.add_field(name="Kazanan", value=f"**{kazanan}**", inline=True)
        e.add_field(name="Bitiş", value=f"<t:{end}:R>", inline=True)
        e.add_field(name="Katılım", value="Çekilişe katılmak için 🎉 tepkisi ver!", inline=False)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Bol şans! 🍀")
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)
        msg = await interaction.original_response()
        await msg.add_reaction("🎉")
        await database.add_giveaway(interaction.guild_id, msg.id, interaction.channel_id, end, kazanan, ödül[:256])

    @app_commands.command(name="oneri", description="Sunucu için öneri paylaşır")
    async def oneri(self, interaction: discord.Interaction, öneri: str):
        cfg = database.guild_config(interaction.guild_id)
        ch_id = cfg.get("suggestions", {}).get("channel_id")
        if not ch_id:
            await interaction.response.send_message(
                embed=ui.alert("error", "Öneri kanalı ayarlanmamış. Yetkili `şuneri_kanal` komutunu kullansın.", interaction=interaction),
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(int(ch_id))
        if not channel:
            await interaction.response.send_message(
                embed=ui.alert("error", "Öneri kanalı bulunamadı.", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Öneri gönderiliyor",
            emoji_="💡",
            color="info",
            steps=4,
            delay=0.16,
        )
        e = ui.embed(
            "Öneri",
            öneri[:4000],
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="💡",
        )
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        msg = await channel.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await database.add_suggestion(interaction.guild_id, msg.id, channel.id, interaction.user.id, öneri[:4000])
        result = ui.embed(
            "Öneri Paylaşıldı",
            f"Önerin **{channel.mention}** kanalında yayınlandı.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="✅",
        )
        result.add_field(name="Bağlantı", value=f"[Tıkla ve gör]({msg.jump_url})", inline=False)
        await edit(embed=ui.apply_animated(result, interaction.guild), content=None)

    @app_commands.command(name="oneri_kanal", description="Öneri kanalını ayarlar")
    @app_commands.checks.has_permissions(administrator=True)
    async def oneri_kanal(self, interaction: discord.Interaction, kanal: discord.TextChannel):
        import json

        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        guilds = cfg.setdefault("guilds", {})
        g = guilds.setdefault(str(interaction.guild_id), {})
        g.setdefault("suggestions", {})["channel_id"] = kanal.id
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        e = ui.embed(
            "Öneri Kanalı",
            f"Öneri kanalı ayarlandı.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="📥",
        )
        e.add_field(name="Kanal", value=kanal.mention, inline=True)
        await ui.animate(interaction, final=e, text="Kaydediliyor", emoji_="📥", color="success", steps=4, delay=0.14)

    @app_commands.command(name="onayla", description="Öneriyi onaylar")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def onayla(self, interaction: discord.Interaction, mesaj: str):
        try:
            msg = await interaction.channel.fetch_message(int(mesaj))
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz mesaj ID'si.", interaction=interaction),
                ephemeral=True,
            )
            return
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        embed.color = discord.Color.green()
        embed.set_footer(text="✅ Onaylandı")
        await msg.edit(embed=ui.apply_animated(embed, interaction.guild))
        await database.set_suggestion_status(int(mesaj), "approved")
        await interaction.response.send_message(
            embed=ui.alert("success", "Öneri onaylandı.", interaction=interaction),
            ephemeral=True,
        )

    @app_commands.command(name="reddet", description="Öneriyi reddeder")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def reddet(self, interaction: discord.Interaction, mesaj: str):
        try:
            msg = await interaction.channel.fetch_message(int(mesaj))
        except (ValueError, discord.HTTPException):
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz mesaj ID'si.", interaction=interaction),
                ephemeral=True,
            )
            return
        embed = msg.embeds[0] if msg.embeds else discord.Embed()
        embed.color = discord.Color.red()
        embed.set_footer(text="❌ Reddedildi")
        await msg.edit(embed=ui.apply_animated(embed, interaction.guild))
        await database.set_suggestion_status(int(mesaj), "rejected")
        await interaction.response.send_message(
            embed=ui.alert("error", "Öneri reddedildi.", interaction=interaction),
            ephemeral=True,
        )

    @app_commands.command(name="etiket", description="Özel komut ekler (metin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def etiket_ekle(self, interaction: discord.Interaction, isim: str, içerik: str):
        await database.save_tag(interaction.guild_id, isim, içerik, interaction.user.id)
        await interaction.response.send_message(
            embed=ui.alert("success", f"`{isim}` etiketi oluşturuldu.", interaction=interaction),
            ephemeral=True,
        )

    @app_commands.command(name="etiket_sil", description="Özel komut siler")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def etiket_sil(self, interaction: discord.Interaction, isim: str):
        await database.delete_tag(interaction.guild_id, isim)
        await interaction.response.send_message(
            embed=ui.alert("success", f"`{isim}` etiketi silindi.", interaction=interaction),
            ephemeral=True,
        )

    @app_commands.command(name="etiketler", description="Tüm etiketleri listeler")
    async def etiketler(self, interaction: discord.Interaction):
        tags = await database.get_tags(interaction.guild_id)
        if not tags:
            await interaction.response.send_message(
                embed=ui.alert("error", "Henüz etiket yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Etiketler",
            "**" + ", ".join(f"`{t}`" for t in tags) + "**",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="📌",
        )
        e.add_field(name="Kullanım", value="`/etiket_goster isim:` ile içeriği görüntüle", inline=False)
        await ui.animate(interaction, final=e, text="Etiketler getiriliyor", emoji_="📌", color="info", steps=4, delay=0.14)

    @app_commands.command(name="etiket_goster", description="Etiket içeriğini gösterir")
    async def etiket_goster(self, interaction: discord.Interaction, isim: str):
        content = await database.get_tag(interaction.guild_id, isim)
        if not content:
            await interaction.response.send_message(
                embed=ui.alert("error", f"`{isim}` etiketi bulunamadı.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            isim,
            content[:2000],
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="📌",
        )
        await ui.animate(interaction, final=e, text="Etiket getiriliyor", emoji_="📌", color="info", steps=4, delay=0.14)


async def setup(bot):
    await bot.add_cog(GiveawayLoop(bot))
    await bot.add_cog(Social(bot))
