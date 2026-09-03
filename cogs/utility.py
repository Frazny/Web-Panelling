import asyncio
import ast
import operator
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expression):
    """Yalnızca sayılar ve aritmetik operatörlere izin veren güvenli değerlendirici.

    ``eval`` yerine AST tabanlıdır: attribute erişimi, çağrı, isim vs. yok.
    ``eval`` kullanıldığında (sandbox kaçışı ile config.json/token sızdırma)
    riskini ortadan kaldırır.
    """
    tree = ast.parse(expression, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError("Sadece sayılar kullanılabilir")
        if isinstance(node, ast.BinOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError("Desteklenmeyen işlem")
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > 1000:
                raise ValueError("Üs çok büyük")
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError("Desteklenmeyen işlem")
            return op(_eval(node.operand))
        raise ValueError("Geçersiz ifade")

    return _eval(tree)


class ReminderLoop(commands.Cog):
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
                rows = await database.get_due_reminders()
                for rid, gid, uid, chid, text in rows:
                    channel = self.bot.get_channel(chid)
                    if channel:
                        try:
                            await channel.send(f"⏰ {self.bot.get_user(uid).mention if self.bot.get_user(uid) else f'<@{uid}>'} Hatırlatma: **{text}**")
                        except discord.Forbidden:
                            pass
                    await database.mark_reminder_done(rid)
            except Exception:
                pass
            await asyncio.sleep(10)


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._start = time.time()

    @app_commands.command(name="hakkında", description="Bot hakkında bilgi gösterir")
    async def hakkinda(self, interaction: discord.Interaction):
        e = ui.embed(
            "Hakkında",
            "Merhaba! Ben bu sunucunun çok amaçlı botuyum.\n\n"
            "🌐 **Web Sitesi:** [frazny.is-a.dev](https://frazny.is-a.dev/)\n\n"
            "Komutlar, moderasyon, ekonomi, müzik ve daha fazlası için buradayım!",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="ℹ️",
        )
        e.add_field(name="Sunucu Sayısı", value=f"**{len(self.bot.guilds)}**", inline=True)
        e.add_field(name="Komut Sayısı", value=f"**{len(self.bot.tree.get_commands())}**", inline=True)
        e.add_field(name="Gecikmesi", value=f"**{round(self.bot.latency * 1000)}ms**", inline=True)
        e.add_field(name="🔗 Link", value="[frazny.is-a.dev](https://frazny.is-a.dev/)", inline=False)
        if self.bot.user:
            e.set_thumbnail(url=self.bot.user.display_avatar.url)
        await ui.animate(interaction, final=e, text="Bilgiler yükleniyor", emoji_="ℹ️", color="info", steps=4, delay=0.12)

    @app_commands.command(name="ping", description="Bot gecikmesini gösterir")
    async def ping(self, interaction: discord.Interaction):
        start = time.perf_counter()
        edit = await ui.animate(
            interaction,
            text="Ping ölçülüyor",
            emoji_="🏓",
            color="teal",
            steps=4,
            delay=0.12,
        )
        latency = round(self.bot.latency * 1000)
        elapsed = round((time.perf_counter() - start) * 1000)
        e = ui.embed(
            "Pong!",
            description=None,
            color="teal",
            interaction=interaction,
            timestamp=True,
            emoji_="🏓",
        )
        e.add_field(name="WebSocket", value=f"**{latency}ms**", inline=True)
        e.add_field(name="Yanıt Süresi", value=f"**{elapsed}ms**", inline=True)
        e.add_field(name="Durum", value="🟢 Mükemmel" if latency < 100 else "🟡 Orta" if latency < 250 else "🔴 Yavaş", inline=True)
        e.add_field(name="Yüklü Cog", value=f"**{len(self.bot.cogs)}**", inline=True)
        e.add_field(name="Komut", value=f"**{len(self.bot.tree.get_commands())}**", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="uptime", description="Botun ne kadar süredir açık olduğunu gösterir")
    async def uptime(self, interaction: discord.Interaction):
        delta = time.time() - self._start
        days, rem = divmod(int(delta), 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        e = ui.embed(
            "Çalışma Süresi",
            f"Bot **{ui.countdown(int(delta))}**'dir kesintisiz çalışıyor.",
            color="teal",
            interaction=interaction,
            timestamp=True,
            emoji_="⏱️",
        )
        e.add_field(name="Gün", value=str(days), inline=True)
        e.add_field(name="Saat", value=str(hours), inline=True)
        e.add_field(name="Dakika", value=str(mins), inline=True)
        e.add_field(name="Saniye", value=str(secs), inline=True)
        e.add_field(name="Sunucu", value=str(len(self.bot.guilds)), inline=True)
        e.add_field(name="Üye", value=str(sum(g.member_count or 0 for g in self.bot.guilds)), inline=True)
        await ui.animate(interaction, final=e, text="Süre hesaplanıyor", emoji_="⏱️", color="teal", steps=4, delay=0.12)

    @app_commands.command(name="avatar", description="Birinin profil resmini gösterir")
    async def avatar(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        user = uye or interaction.user
        e = ui.embed(
            f"Profil Resmi — {user.display_name}",
            f"**[Açık büyüt]({user.display_avatar.url})**",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🖼️",
        )
        e.set_image(url=user.display_avatar.url)
        e.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • Tam boyutu görmek için görsele tıkla")
        await ui.animate(interaction, final=e, text="Avatar getiriliyor", emoji_="🖼️", color="info", steps=4, delay=0.12)

    @app_commands.command(name="banner", description="Birinin banner'ını gösterir")
    async def banner(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        user = uye or interaction.user
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Banner aranıyor",
            emoji_="🖼️",
            color="info",
            steps=4,
            delay=0.15,
        )
        user = await self.bot.fetch_user(user.id)
        if not user.banner:
            await edit(embed=ui.apply_animated(ui.alert("warn", "Bu kullanıcının banner'ı yok.", interaction=interaction), interaction.guild), content=None)
            return
        e = ui.embed(
            f"Banner — {user.display_name}",
            f"**[Açık büyüt]({user.banner.url})**",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🖼️",
        )
        e.set_image(url=user.banner.url)
        e.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="userinfo", description="Kullanıcı bilgilerini gösterir")
    async def userinfo(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        member = uye or interaction.user
        e = ui.embed(
            "Kullanıcı Bilgileri",
            description=None,
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="👤",
        )
        e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Kullanıcı", value=f"{member.mention}\n`{member.id}`", inline=True)
        e.add_field(name="Katılım", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "-", inline=True)
        e.add_field(name="Hesap", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        status = member.status.name if member.status else "-"
        e.add_field(name="Durum", value={"online": "🟢 Çevrimiçi", "idle": "🟡 Boşta", "dnd": "🔴 Rahatsız Etmeyin", "offline": "⚫ Çevrimdışı"}.get(status, status), inline=True)
        e.add_field(name="Aktiflik", value=f"<t:{int(member.created_at.timestamp())}:R>" if (discord.utils.utcnow() - member.created_at).days > 0 else "-", inline=True)
        roles = member.roles[1:]
        e.add_field(name=f"Roller ({len(roles)})", value=", ".join(r.mention for r in roles[:5]) or "-", inline=False)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • En yüksek rol: {member.top_role.name}")
        await ui.animate(interaction, final=e, text="Bilgiler toplanıyor", emoji_="👤", color="info", steps=5, delay=0.14)

    @app_commands.command(name="serverinfo", description="Sunucu bilgilerini gösterir")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        humans = len([m for m in g.members if not m.bot])
        bots = g.member_count - humans
        e = ui.embed(
            g.name,
            description=None,
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🏰",
        )
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="👑 Sahip", value=g.owner.mention if g.owner else "-", inline=True)
        e.add_field(name="👥 Toplam Üye", value=str(g.member_count), inline=True)
        e.add_field(name="🧑 İnsan / 🤖 Bot", value=f"{humans} / {bots}", inline=True)
        e.add_field(name="💬 Kanal", value=f"{len(g.text_channels)} metin / {len(g.voice_channels)} ses", inline=True)
        e.add_field(name="🎭 Rol", value=str(len(g.roles)), inline=True)
        e.add_field(name="📅 Kuruluş", value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
        e.add_field(name="🆔 ID", value=f"`{g.id}`", inline=True)
        boosts = g.premium_subscription_count
        e.add_field(name="🚀 Boost", value=str(boosts), inline=True)
        e.add_field(name="💾 Seviye", value=str(g.verification_level), inline=True)
        e.add_field(name="📶 2FA", value="✅ Gerekli" if g.mfa_level else "❌ Gerekli değil", inline=True)
        await ui.animate(interaction, final=e, text="Sunucu bilgileri toplanıyor", emoji_="🏰", color="info", steps=5, delay=0.14)

    @app_commands.command(name="roleinfo", description="Rol bilgilerini gösterir")
    async def roleinfo(self, interaction: discord.Interaction, rol: discord.Role):
        e = ui.embed(
            rol.name,
            description=None,
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🎭",
        )
        e.color = rol.color if rol.color.value else ui.color("info")
        e.add_field(name="ID", value=f"`{rol.id}`", inline=True)
        e.add_field(name="Renk", value=f"`{rol.color}`", inline=True)
        e.add_field(name="Üye Sayısı", value=str(len(rol.members)), inline=True)
        e.add_field(name="Ayrı Görünüm", value="✅" if rol.hoist else "❌", inline=True)
        e.add_field(name="Etiketlenebilir", value="✅" if rol.mentionable else "❌", inline=True)
        e.add_field(name="Yönetilen", value="✅" if rol.managed else "❌", inline=True)
        e.add_field(name="Pozisyon", value=str(rol.position), inline=True)
        izin = "`" + ", ".join(k.replace("_", " ") for k, v in rol.permissions if v)[:200] + "`"
        e.add_field(name="İzinler", value=izin or "Yok", inline=False)
        await ui.animate(interaction, final=e, text="Rol bilgileri toplanıyor", emoji_="🎭", color="info", steps=4, delay=0.14)

    @app_commands.command(name="embed", description="Özel embed mesaj oluşturur")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed(self, interaction: discord.Interaction, başlık: str, içerik: str):
        e = ui.embed(
            başlık[:256],
            içerik[:4000],
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="📝",
        )
        await ui.animate(interaction, final=e, text="Embed hazırlanıyor", emoji_="📝", color="info", steps=4, delay=0.12)

    @app_commands.command(name="afk", description="AFK durumunu ayarlar")
    async def afk(self, interaction: discord.Interaction, sebep: str | None = None):
        reason = sebep or "AFK"
        await database.set_afk(interaction.guild_id, interaction.user.id, reason)
        e = ui.embed(
            "AFK Modu Aktif",
            f"{interaction.user.mention} artık AFK. Birine etiketlenirsen bu mesajla dönerim:",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="😴",
        )
        e.add_field(name="Sebep", value=f"```{reason}```", inline=False)
        await ui.animate(interaction, final=e, text="AFK ayarlanıyor", emoji_="😴", color="info", steps=4, delay=0.12)

    @app_commands.command(name="hesapla", description="Basit matematik hesabı yapar")
    async def hesapla(self, interaction: discord.Interaction, ifade: str):
        expr = ifade.replace("x", "*").replace("×", "*").replace("÷", "/").replace("^", "**")
        try:
            if len(expr) > 100:
                raise ValueError("İfade çok uzun")
            result = _safe_eval(expr)
            if isinstance(result, float):
                if result != result or result in (float("inf"), float("-inf")):
                    raise ValueError("Geçersiz sonuç")
                result = round(result, 10)
            if len(str(result)) > 400:
                raise ValueError("Sonuç çok büyük")
        except (ValueError, SyntaxError, OverflowError, ZeroDivisionError):
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz ifade. Sadece sayılar ve + - * / // % ** işlemleri kullanılabilir.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Hesaplama Sonucu",
            description=None,
            color="teal",
            interaction=interaction,
            timestamp=True,
            emoji_="🧮",
        )
        e.add_field(name="İfade", value=f"```{ifade}```", inline=False)
        e.add_field(name="Sonuç", value=f"**{result}**", inline=False)
        await ui.animate(interaction, final=e, text="Hesaplanıyor", emoji_="🧮", color="teal", steps=4, delay=0.12)

    @app_commands.command(name="8ball", description="Sihirli 8 top sorunu cevaplar")
    async def eightball(self, interaction: discord.Interaction, soru: str):
        answers = [
            "Kesinlikle evet.", "Büyük ihtimalle evet.", "Görünüşe göre evet.",
            "Şimdilik söyleyemem.", "Kesin değil.", "Kaynaklarıma göre hayır.",
            "Büyük ihtimalle hayır.", "Asla!", "Tekrar dene.",
        ]
        edit = await ui.animate(
            interaction,
            text="Sihirli top düşünüyor",
            emoji_="🎱",
            color="purple",
            detail=soru[:100],
            steps=6,
            delay=0.22,
        )
        e = ui.embed(
            "Sihirli 8 Top",
            description=None,
            color="purple",
            interaction=interaction,
            timestamp=True,
            emoji_="🎱",
        )
        e.add_field(name="Soru", value=f"```{soru}```", inline=False)
        e.add_field(name="Cevap", value=f"**{random.choice(answers)}**", inline=False)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="yazitura", description="Yazı tura atar")
    async def yazitura(self, interaction: discord.Interaction):
        edit = await ui.animate(
            interaction,
            text="Para havada",
            emoji_="🪙",
            color="gold",
            steps=6,
            delay=0.2,
        )
        result = random.choice(["Yazı", "Tura"])
        e = ui.embed(
            "Yazı Tura",
            f"🪙 Para döndü ve **{result}** geldi!",
            color="gold",
            interaction=interaction,
            timestamp=True,
            emoji_="🪙",
        )
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="tkm", description="Taş kağıt makas oynar")
    async def tkm(self, interaction: discord.Interaction, seçim: str):
        choices = ["taş", "kağıt", "makas"]
        if seçim.lower() not in choices:
            await interaction.response.send_message(
                embed=ui.alert("error", "`taş`, `kağıt` veya `makas` seçmelisin.", interaction=interaction),
                ephemeral=True,
            )
            return
        icons = {"taş": "🪨", "kağıt": "📄", "makas": "✂️"}
        edit = await ui.animate(
            interaction,
            text="TKM oynanıyor",
            emoji_="✋",
            color="pink",
            detail=f"Senin seçimin: {icons[seçim.lower()]}",
            steps=5,
            delay=0.18,
        )
        bot = random.choice(choices)
        beats = {"taş": "makas", "kağıt": "taş", "makas": "kağıt"}
        if seçim.lower() == bot:
            result, color = "🤝 Berabere!", "info"
        elif beats[seçim.lower()] == bot:
            result, color = "🎉 Kazandın!", "success"
        else:
            result, color = "😔 Kaybettin!", "error"
        e = ui.embed(
            "Taş Kağıt Makas",
            description=None,
            color=color,
            interaction=interaction,
            timestamp=True,
            emoji_="🎮",
        )
        e.add_field(name="Sen", value=f"{icons[seçim.lower()]} **{seçim}**", inline=True)
        e.add_field(name="Bot", value=f"{icons[bot]} **{bot}**", inline=True)
        e.add_field(name="Sonuç", value=f"**{result}**", inline=False)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="şaka", description="Rastgele bir şaka söyler")
    async def saka(self, interaction: discord.Interaction):
        jokes = [
            "Programcılar neden gözlük takar? Çünkü C#'ı iyi göremezler.",
            "İki bayt buluşmuş: 'Sen bana böyle bit demiştin?'",
            "Neden yazılımcılar karanlıktan korkar? Çünkü bug'lar ışığı sevmez.",
            "Bir yönetici sorar: 'Kaç programcı gerekir bir ampulü değiştirmek için?' Cevap: Hiç, o bir donanım sorunu.",
            "Neden bilgisayar zayıflayamaz? Çünkü hep önbellekte (cache) yemek yer.",
        ]
        edit = await ui.animate(
            interaction,
            text="Şaka hazırlanıyor",
            emoji_="😂",
            color="pink",
            steps=4,
            delay=0.12,
        )
        e = ui.embed(
            "Bir Fıkra",
            random.choice(jokes),
            color="pink",
            interaction=interaction,
            timestamp=True,
            emoji_="😂",
        )
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @app_commands.command(name="hatirlat", description="Kendine zamanlanmış hatırlatma kurar")
    async def hatirlat(self, interaction: discord.Interaction, süre: str, mesaj: str):
        units = {"s": 1, "d": 86400, "sa": 3600, "saat": 3600, "dk": 60, "dakika": 60, "g": 86400, "gün": 86400}
        try:
            amount = int("".join(c for c in süre if c.isdigit()))
            unit = "".join(c for c in süre if not c.isdigit()).lower()
            seconds = amount * units.get(unit, 1)
        except Exception:
            await interaction.response.send_message(
                embed=ui.alert("error", "Geçersiz süre. Örn: `10dk`, `2sa`, `1g`", interaction=interaction),
                ephemeral=True,
            )
            return
        if seconds <= 0 or seconds > 31536000:
            await interaction.response.send_message(
                embed=ui.alert("error", "Süre 1 saniye ile 1 yıl arasında olmalı.", interaction=interaction),
                ephemeral=True,
            )
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Hatırlatma kuruluyor",
            emoji_="⏰",
            color="info",
            steps=4,
            delay=0.14,
        )
        await database.add_reminder(interaction.guild_id, interaction.user.id, interaction.channel_id, int(time.time()) + seconds, mesaj[:1000])
        e = ui.embed(
            "Hatırlatma Kuruldu",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="⏰",
        )
        e.add_field(name="Süre", value=f"**{ui.countdown(seconds)}**", inline=True)
        e.add_field(name="Zaman", value=f"<t:{int(time.time()) + seconds}:R>", inline=True)
        e.add_field(name="Mesaj", value=f"```{mesaj[:1000]}```", inline=False)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        prefix = database.guild_config(message.guild.id).get("prefix", "!")
        if message.content.startswith(prefix):
            return
        afk_data = await database.get_afk(message.guild.id, message.author.id)
        if afk_data:
            await database.remove_afk(message.guild.id, message.author.id)
            await message.channel.send(f"👋 Hoş geldin {message.author.mention}, AFK'dan döndün!", delete_after=5)
        for user in message.mentions:
            data = await database.get_afk(message.guild.id, user.id)
            if data and user.id != message.author.id:
                await message.channel.send(
                    f"🔕 {user.mention} şu an AFK: **{data['reason']}**",
                    delete_after=10,
                )
                break


async def setup(bot):
    await bot.add_cog(ReminderLoop(bot))
    await bot.add_cog(Utility(bot))
