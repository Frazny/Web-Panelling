import asyncio
import random
import time
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

import database
from database import load_config
from utils import ui


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._locks = defaultdict(asyncio.Lock)

    def _cfg(self):
        return load_config().get("economy", {})

    async def _check_cooldown(self, guild_id, user_id, claim):
        expires = await database.get_cooldown(guild_id, user_id, claim)
        now = int(time.time())
        if expires and now < expires:
            return expires - now
        return 0

    async def _rank(self, guild_id, user_id):
        rows = await database.get_balance_leaderboard(guild_id, limit=999999)
        for i, (uid, _bal) in enumerate(rows, start=1):
            if uid == user_id:
                return i, len(rows)
        return None, len(rows)

    @app_commands.command(name="bakiye", description="Bakiyeni veya birinin bakiyesini gösterir")
    async def bakiye(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        user = uye or interaction.user
        balance = await database.get_balance(interaction.guild_id, user.id)
        rank, total = await self._rank(interaction.guild_id, user.id)
        e = ui.embed(
            "Bakiye",
            f"{user.mention} kullanıcısının cüzdanı:",
            color="money",
            interaction=interaction,
            timestamp=True,
            emoji_="💰",
        )
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name="Bakiye", value=f"**{balance:,}** 💎", inline=True)
        e.add_field(name="Sıralama", value=f"#{rank} / {total}" if rank else "—", inline=True)
        e.add_field(name="Durum", value="🟢 Zengin" if balance >= 10_000 else "🟡 Orta" if balance >= 1_000 else "🔴 Çaylak", inline=True)
        await ui.animate(interaction, final=e, text="Bakiye getiriliyor", emoji_="💰", color="money", steps=4, delay=0.15)

    @app_commands.command(name="gunluk", description="Günlük ödülünü alır")
    async def gunluk(self, interaction: discord.Interaction):
        cfg = self._cfg()
        amount = cfg.get("daily", 250)
        wait = await self._check_cooldown(interaction.guild_id, interaction.user.id, "daily")
        if wait:
            await interaction.response.send_message(
                embed=ui.alert(
                    "warn",
                    f"Günlük ödülünü almak için **{ui.countdown(wait)}** daha beklemelisin.\n{ui.bar(wait, 86400, width=16)}",
                    interaction=interaction,
                    title="⏳ Sabırlı ol",
                ),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Ödül hazırlanıyor",
            emoji_="🎁",
            color="money",
            steps=5,
            delay=0.2,
        )
        new = await database.add_balance(interaction.guild_id, interaction.user.id, amount)
        await database.set_cooldown(interaction.guild_id, interaction.user.id, "daily", int(time.time()) + 86400)
        e = ui.embed(
            "Günlük Ödül Alındı",
            f"🎉 Tebrikler {interaction.user.mention}! Günlük ödülün cüzdanına eklendi.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🎁",
        )
        e.add_field(name="Alınan", value=f"**+{amount:,}** 💎", inline=True)
        e.add_field(name="Yeni Bakiye", value=f"**{new:,}** 💎", inline=True)
        e.add_field(name="Sonraki Ödül", value=f"<t:{int(time.time()) + 86400}:R>", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="haftalik", description="Haftalık ödülünü alır")
    async def haftalik(self, interaction: discord.Interaction):
        cfg = self._cfg()
        amount = cfg.get("weekly", 1000)
        wait = await self._check_cooldown(interaction.guild_id, interaction.user.id, "weekly")
        if wait:
            await interaction.response.send_message(
                embed=ui.alert(
                    "warn",
                    f"Haftalık ödülünü almak için **{ui.countdown(wait)}** daha beklemelisin.\n{ui.bar(wait, 604800, width=16)}",
                    interaction=interaction,
                    title="⏳ Sabırlı ol",
                ),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Haftalık ödül hazırlanıyor",
            emoji_="🎁",
            color="money",
            steps=5,
            delay=0.2,
        )
        new = await database.add_balance(interaction.guild_id, interaction.user.id, amount)
        await database.set_cooldown(interaction.guild_id, interaction.user.id, "weekly", int(time.time()) + 604800)
        e = ui.embed(
            "Haftalık Ödül Alındı",
            f"🎉 Haftanın ödülü {interaction.user.mention} için geldi!",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🎁",
        )
        e.add_field(name="Alınan", value=f"**+{amount:,}** 💎", inline=True)
        e.add_field(name="Yeni Bakiye", value=f"**{new:,}** 💎", inline=True)
        e.add_field(name="Sonraki Ödül", value=f"<t:{int(time.time()) + 604800}:R>", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="is", description="Çalış ve rastgele para kazan")
    async def is_komutu(self, interaction: discord.Interaction):
        wait = await self._check_cooldown(interaction.guild_id, interaction.user.id, "work")
        if wait:
            await interaction.response.send_message(
                embed=ui.alert(
                    "warn",
                    f"Tekrar çalışmak için **{ui.countdown(wait)}** beklemen gerekiyor.\n{ui.bar(wait, 3600, width=16)}",
                    interaction=interaction,
                    title="⏳ Mola ver",
                ),
                ephemeral=True,
            )
            return
        jobs = [
            ("ofiste kod yazdın", "💻", 150, 400),
            ("kafede garsonluk yaptın", "☕", 80, 200),
            ("inşaatta çalıştın", "🏗️", 120, 350),
            ("kütüphanede kitap dizdin", "📚", 60, 180),
            ("mağazada kasiyerlik yaptın", "🛒", 90, 250),
            ("taksiyle yolcu taşıdın", "🚕", 100, 300),
            ("bahçede çalıştın", "🌻", 70, 220),
        ]
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Mesai yapılıyor",
            emoji_="💼",
            color="money",
            detail="İş bulunuyor…",
            steps=5,
            delay=0.2,
        )
        action, icon, lo, hi = random.choice(jobs)
        amount = random.randint(lo, hi)
        new = await database.add_balance(interaction.guild_id, interaction.user.id, amount)
        await database.set_cooldown(interaction.guild_id, interaction.user.id, "work", int(time.time()) + 3600)
        e = ui.embed(
            "İş Tamamlandı",
            f"{icon} Bir {action} ve **+{amount:,}** 💎 kazandın!",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="💼",
        )
        e.add_field(name="Kazanç", value=f"**+{amount:,}** 💎", inline=True)
        e.add_field(name="Yeni Bakiye", value=f"**{new:,}** 💎", inline=True)
        e.add_field(name="Tekrar Çalış", value=f"<t:{int(time.time()) + 3600}:R>", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="casino", description="50/50 şansla para ikiye katla veya kaybet")
    async def casino(self, interaction: discord.Interaction, miktar: app_commands.Range[int, 1, 1_000_000]):
        async with self._locks[interaction.user.id]:
            balance = await database.get_balance(interaction.guild_id, interaction.user.id)
            if miktar > balance:
                await interaction.response.send_message(
                    embed=ui.alert(
                        "error",
                        f"Yetersiz bakiye. Mevcut bakiyen: **{balance:,}** 💎",
                        interaction=interaction,
                        title="Kumar hırsızı 😅",
                    ),
                    ephemeral=True,
                )
                return
            edit = await ui.animate(
                interaction,
                defer=True,
                text="Zar atılıyor",
                emoji_="🎰",
                color="pink",
                detail=f"Bahis: **{miktar:,}** 💎",
                steps=7,
                delay=0.25,
            )
            won = random.random() < 0.5
            new = await database.add_balance(interaction.guild_id, interaction.user.id, miktar if won else -miktar)
        e = ui.embed(
            "Casino Sonucu",
            description=None,
            color="success" if won else "error",
            interaction=interaction,
            timestamp=True,
            emoji_="🍀" if won else "💸",
        )
        e.add_field(name="Sonuç", value="**KAZANDIN!** 🎉" if won else "**KAYBETTİN!** 😭", inline=True)
        e.add_field(name="Değişim", value=f"**{'+' if won else '-'}{miktar:,}** 💎", inline=True)
        e.add_field(name="Yeni Bakiye", value=f"**{new:,}** 💎", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="transfer", description="Birine para gönder")
    async def transfer(self, interaction: discord.Interaction, uye: discord.Member, miktar: app_commands.Range[int, 1, 1_000_000]):
        if uye.bot:
            await interaction.response.send_message(
                embed=ui.alert("error", "Botlara para gönderemezsin.", interaction=interaction), ephemeral=True
            )
            return
        if uye.id == interaction.user.id:
            await interaction.response.send_message(
                embed=ui.alert("error", "Kendine para gönderemezsin.", interaction=interaction), ephemeral=True
            )
            return
        async with self._locks[interaction.user.id]:
            balance = await database.get_balance(interaction.guild_id, interaction.user.id)
            if miktar > balance:
                await interaction.response.send_message(
                    embed=ui.alert(
                        "error",
                        f"Yetersiz bakiye. Mevcut bakiyen: **{balance:,}** 💎",
                        interaction=interaction,
                    ),
                    ephemeral=True,
                )
                return
            edit = await ui.animate(
                interaction,
                defer=True,
                text="Havale yapılıyor",
                emoji_="💸",
                color="money",
                detail=f"{interaction.user.mention} → {uye.mention}",
                steps=5,
                delay=0.2,
            )
            await database.add_balance(interaction.guild_id, interaction.user.id, -miktar)
            new_target = await database.add_balance(interaction.guild_id, uye.id, miktar)
            new_sender = await database.get_balance(interaction.guild_id, interaction.user.id)
        e = ui.embed(
            "Transfer Tamamlandı",
            f"{interaction.user.mention} → {uye.mention}",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="💸",
        )
        e.add_field(name="Miktar", value=f"**{miktar:,}** 💎", inline=True)
        e.add_field(name="Gönderen Bakiye", value=f"**{new_sender:,}** 💎", inline=True)
        e.add_field(name="Alan Bakiye", value=f"**{new_target:,}** 💎", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="toppara", description="En zengin üyeleri gösterir")
    async def toppara(self, interaction: discord.Interaction):
        rows = await database.get_balance_leaderboard(interaction.guild_id, 10)
        if not rows:
            await interaction.response.send_message(
                embed=ui.alert("error", "Henüz veri yok.", interaction=interaction), ephemeral=True
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, bal) in enumerate(rows):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"<@{uid}>"
            mark = medals[i] if i < 3 else f"`{i+1}.`"
            max_bal = max(b for _, b in rows)
            lines.append(f"{mark} {name} — **{bal:,}** 💎\n{ui.bar(bal, max_bal, width=12)}")
        e = ui.embed(
            "Para Liderlik Tablosu",
            "\n\n".join(lines),
            color="gold",
            interaction=interaction,
            timestamp=True,
            emoji_="🏆",
        )
        await ui.animate(interaction, final=e, text="Sıralama yükleniyor", emoji_="🏆", color="gold", steps=4, delay=0.15)


async def setup(bot):
    await bot.add_cog(Economy(bot))
