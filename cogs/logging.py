import datetime
import math

import discord
from discord import app_commands
from discord import AuditLogAction
from discord.ext import commands

import database
from utils import ui
from utils.checks import is_owner

_BADGE_NAMES = {
    "staff": "Discord Staff",
    "partner": "Discord Partner",
    "hypesquad": "HypeSquad",
    "bug_hunter": "Bug Hunter",
    "hypesquad_bravery": "HypeSquad Bravery",
    "hypesquad_brilliance": "HypeSquad Brilliance",
    "hypesquad_balance": "HypeSquad Balance",
    "early_supporter": "Erken Destekçi",
    "bug_hunter_level_2": "Bug Hunter (Elit)",
    "verified_bot_developer": "Doğrulanmış Bot Geliştiricisi",
    "active_developer": "Aktif Geliştirici",
    "verified_developer": "Erken Doğrulanmış Bot Geliştiricisi",
    "certified_moderator": "Sertifikalı Moderatör",
}


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.snipes = {}

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

    async def _log_channel(self, guild):
        cfg = database.guild_config(guild.id)
        ch_id = cfg.get("logs", {}).get("channel_id")
        if not ch_id:
            ch_id = await database.get_setting(guild.id, "log_channel", None)
        if not ch_id:
            ch_id = cfg.get("moderation", {}).get("mod_log_channel", 0)
        return guild.get_channel(int(ch_id)) if ch_id else None

    async def _log(self, guild, title, description, color=discord.Color.blurple()):
        channel = await self._log_channel(guild)
        await self._log_to(channel, guild, title, description, color)

    async def _log_to(self, channel, guild, title, description, color=discord.Color.blurple()):
        if not channel:
            return
        embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.now())
        embed.set_footer(text=f"{guild.name if guild else ''} • Log Sistemi", icon_url=guild.icon.url if guild and guild.icon else None)
        ui.apply_animated(embed, guild)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _cfg_channel(self, guild, key):
        cfg = database.guild_config(guild.id)
        ch_id = (cfg.get("logs") or {}).get(key)
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                return ch
        ch_id = await database.get_setting(guild.id, key, None)
        if ch_id:
            return guild.get_channel(int(ch_id))
        return None

    async def _voice_log_channel(self, guild):
        return (await self._cfg_channel(guild, "voice_channel_id")) or await self._log_channel(guild)

    async def _punish_log_channel(self, guild):
        return (await self._cfg_channel(guild, "punish_channel_id")) or await self._log_channel(guild)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        self.snipes[message.channel.id] = {"author": message.author, "content": message.content}
        if message.content:
            await self._log(
                message.guild,
                "🗑️ Mesaj Silindi",
                f"**Kanal:** {message.channel.mention}\n**Yazan:** {message.author.mention}\n**Mesaj:** {message.content}",
                discord.Color.red(),
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        await self._log(
            before.guild,
            "✏️ Mesaj Düzenlendi",
            f"**Kanal:** {before.channel.mention}\n**Yazan:** {before.author.mention}\n**Önce:** {before.content}\n**Sonra:** {after.content}",
            discord.Color.orange(),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.guild:
            return
        ch = await self._join_log_channel(member.guild)
        if ch is None:
            return
        try:
            await ch.send(embed=await self._build_join_embed(member))
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if not member.guild:
            return
        entry = await self._kick_actor(member)
        if entry is not None:
            await self._log_kick(member, entry)
        await self._log_member_leave(member, entry)

    @staticmethod
    def _badges(member):
        names = []
        for flag in member.public_flags.all():
            names.append(_BADGE_NAMES.get(flag.name, flag.name.replace("_", " ").title()))
        return ", ".join(names)

    @staticmethod
    def _duration(seconds):
        seconds = int(max(0, seconds))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days} gün")
        if hours:
            parts.append(f"{hours} saat")
        if mins:
            parts.append(f"{mins} dakika")
        if secs:
            parts.append(f"{secs} saniye")
        return ", ".join(parts) or "0 saniye"

    async def _leave_log_channel(self, guild):
        """Ayrılış log kanalı: ``logs.leave_channel_id`` (config) → ``leave_log_channel`` (ayar) → varsayılan log kanalı."""
        ch = await self._cfg_channel(guild, "leave_channel_id")
        if ch:
            return ch
        ch_id = await database.get_setting(guild.id, "leave_log_channel", None)
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if isinstance(ch, discord.TextChannel):
                return ch
        return await self._log_channel(guild)

    async def _join_log_channel(self, guild):
        """Katılış log kanalı: ``logs.join_channel_id`` (config) → ``join_log_channel`` (ayar) → ayrılış kanalı → varsayılan log kanalı."""
        ch = await self._cfg_channel(guild, "join_channel_id")
        if ch:
            return ch
        ch_id = await database.get_setting(guild.id, "join_log_channel", None)
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if isinstance(ch, discord.TextChannel):
                return ch
        return await self._leave_log_channel(guild)

    async def _build_join_embed(self, member):
        guild = member.guild
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = int(now.timestamp())

        roles = [r for r in member.roles if not r.is_default()]
        role_mentions = ", ".join(r.mention for r in roles)[:1024] or "(rolü yok)"

        color = member.color
        if color.value == 0:
            color = discord.Color(0x99AAB5)

        flags = self._badges(member)
        created = int(member.created_at.timestamp()) if member.created_at else None

        xp = await database.get_xp(guild.id, member.id)
        level = int(math.sqrt(max(xp, 0) / 100))
        balance = await database.get_balance(guild.id, member.id)
        warns = await database.get_warns(guild.id, member.id)
        joiner = await database.get_joiner(guild.id, member.id)

        e = discord.Embed(
            title="🟢 Üye Katıldı",
            description=f"{member.mention} sunucuya katıldı.",
            color=discord.Color(0x57F287),
            timestamp=now,
        )
        e.set_author(name=f"{member} • {guild.name}", icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)

        e.add_field(name="👤 Üye", value=member.mention, inline=True)
        e.add_field(name="🆔 Kullanıcı ID", value=f"`{member.id}`", inline=True)
        e.add_field(name="🤖 Bot Hesabı", value="Evet 🤖" if member.bot else "Hayır", inline=True)
        e.add_field(name="🏷️ Kullanıcı Adı", value=member.name, inline=True)
        e.add_field(
            name="💬 Sunucu Takma Adı",
            value=member.display_name if member.display_name != member.name else "(yok)",
            inline=True,
        )
        e.add_field(name="🎨 Ana Renk", value=str(color), inline=True)

        if flags:
            e.add_field(name="🏅 Rozetler", value=flags, inline=False)

        e.add_field(
            name="📅 Hesap Açılışı",
            value=f"<t:{created}:F>\n(<t:{created}:R>)" if created else "Bilinmiyor",
            inline=True,
        )
        e.add_field(
            name="💎 Booster",
            value=f"Evet (ta <t:{int(member.premium_since.timestamp())}:d>)" if member.premium_since else "Hayır",
            inline=True,
        )

        e.add_field(name=f"🎭 Rolleri ({len(roles)})", value=role_mentions, inline=False)
        e.add_field(name="📈 Seviye", value=f"**{level}** · `{xp:,}` XP", inline=True)
        e.add_field(name="💰 Bakiye", value=f"**{balance:,}** 💎", inline=True)
        e.add_field(name="⚠️ Uyarı Sayısı", value=f"**{len(warns)}**", inline=True)

        if joiner:
            e.add_field(name="📨 Davet Eden", value=f"<@{joiner['inviter_id']}>", inline=True)

        e.add_field(name="👥 Güncel Üye Sayısı", value=str(guild.member_count), inline=True)
        e.add_field(name="🕐 Katılış Zamanı", value=f"<t:{ts}:F>", inline=True)
        e.set_footer(
            text=f"{guild.name} • Katılış Log",
            icon_url=guild.icon.url if guild.icon else None,
        )
        ui.apply_animated(e, guild)
        return e

    async def _log_member_leave(self, member, entry=None):
        guild = member.guild
        ch = await self._leave_log_channel(guild)
        if ch is None:
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            await ch.send(embed=await self._build_leave_embed(member, entry, now))
        except discord.Forbidden:
            pass

    async def _build_leave_embed(self, member, entry, now):
        guild = member.guild
        ts = int(now.timestamp())

        roles = [r for r in member.roles if not r.is_default()]
        role_mentions = ", ".join(r.mention for r in roles)[:1024] or "(rolü yok)"

        color = member.color
        if color.value == 0:
            color = discord.Color(0x99AAB5)

        flags = self._badges(member)
        created = int(member.created_at.timestamp()) if member.created_at else None
        joined = member.joined_at

        xp = await database.get_xp(guild.id, member.id)
        level = int(math.sqrt(max(xp, 0) / 100))
        balance = await database.get_balance(guild.id, member.id)
        warns = await database.get_warns(guild.id, member.id)
        joiner = await database.get_joiner(guild.id, member.id)

        e = discord.Embed(
            title="🔴 Üye Sunucudan Ayrıldı",
            description=f"{member.mention} artık sunucuda değil.",
            color=discord.Color(0xE74C3C),
            timestamp=now,
        )
        e.set_author(name=f"{member} • {guild.name}", icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)

        e.add_field(name="👤 Üye", value=member.mention, inline=True)
        e.add_field(name="🆔 Kullanıcı ID", value=f"`{member.id}`", inline=True)
        e.add_field(name="🤖 Bot Hesabı", value="Evet 🤖" if member.bot else "Hayır", inline=True)
        e.add_field(name="🏷️ Kullanıcı Adı", value=member.name, inline=True)
        e.add_field(
            name="💬 Sunucu Takma Adı",
            value=member.display_name if member.display_name != member.name else "(yok)",
            inline=True,
        )
        e.add_field(name="🎨 Ana Renk", value=str(color), inline=True)

        if flags:
            e.add_field(name="🏅 Rozetler", value=flags, inline=False)

        e.add_field(
            name="📅 Hesap Açılışı",
            value=f"<t:{created}:F>\n(<t:{created}:R>)" if created else "Bilinmiyor",
            inline=True,
        )
        if joined:
            stay = self._duration((now - joined).total_seconds())
            e.add_field(
                name="📅 Sunucuya Katılış",
                value=f"<t:{int(joined.timestamp())}:F>\n(<t:{int(joined.timestamp())}:R>)",
                inline=True,
            )
            e.add_field(name="⏳ Sunucuda Geçirilen Süre", value=stay, inline=True)
        e.add_field(
            name="💎 Booster",
            value=f"Evet (ta <t:{int(member.premium_since.timestamp())}:d>)" if member.premium_since else "Hayır",
            inline=True,
        )

        e.add_field(name=f"🎭 Rolleri ({len(roles)})", value=role_mentions, inline=False)
        e.add_field(name="📈 Seviye", value=f"**{level}** · `{xp:,}` XP", inline=True)
        e.add_field(name="💰 Bakiye", value=f"**{balance:,}** 💎", inline=True)
        e.add_field(name="⚠️ Uyarı Sayısı", value=f"**{len(warns)}**", inline=True)

        if joiner:
            e.add_field(name="📨 Davet Eden", value=f"<@{joiner['inviter_id']}>", inline=True)

        if entry is not None:
            mod = entry.user
            e.add_field(name="🚪 Ayrılma Nedeni", value="Sunucudan **atıldı (kick)** 👢", inline=True)
            e.add_field(name="🛡️ Atan Yetkili", value=mod.mention if mod else "Bilinmiyor", inline=True)
            e.add_field(name="📝 Kick Gerekçesi", value=entry.reason or "Belirtilmedi", inline=False)
        else:
            e.add_field(name="🚪 Ayrılma Nedeni", value="Kendisi ayrıldı", inline=True)

        e.add_field(name="👥 Güncel Üye Sayısı", value=str(guild.member_count), inline=True)
        e.add_field(name="🕐 Ayrılma Zamanı", value=f"<t:{ts}:F>", inline=True)
        e.set_footer(
            text=f"{guild.name} • Ayrılış Log",
            icon_url=guild.icon.url if guild.icon else None,
        )
        ui.apply_animated(e, guild)
        return e

    async def _kick_log_channel(self, guild):
        return await self._punish_log_channel(guild)

    async def _kick_actor(self, member):
        try:
            async for entry in member.guild.audit_logs(limit=5, action=AuditLogAction.kick):
                if entry.target and entry.target.id == member.id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    async def _log_kick(self, member, entry):
        guild = member.guild
        channel = await self._kick_log_channel(guild)
        if not channel:
            return
        mod = entry.user
        when = entry.created_at or datetime.datetime.now(datetime.timezone.utc)
        ts = int(when.timestamp())
        roles = [r.mention for r in member.roles if not r.is_default()] or ["(rolü yok)"]

        e = discord.Embed(
            title="👢 Üye Sunucudan Atıldı",
            color=discord.Color(0xE67E22),
            timestamp=when,
        )
        e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        e.add_field(name="🚪 Atılan Üye", value=member.mention, inline=True)
        e.add_field(name="🛡️ Atan Yetkili", value=mod.mention if mod else "Bilinmiyor", inline=True)
        e.add_field(name="🆔 Üye ID", value=f"`{member.id}`", inline=True)
        e.add_field(
            name="🕐 Atılma Zamanı",
            value=f"<t:{ts}:F>\n`{when.strftime('%d.%m.%Y %H:%M:%S')}`",
            inline=False,
        )
        e.add_field(name="📝 Gerekçe", value=entry.reason or "Belirtilmedi", inline=False)
        if member.created_at:
            e.add_field(name="📅 Hesap Açılışı", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=True)
        if member.joined_at:
            e.add_field(name="📅 Sunucuya Katılım", value=f"<t:{int(member.joined_at.timestamp())}:D>", inline=True)
        e.add_field(
            name=f"🎭 Rolleri ({len(member.roles) - 1})",
            value=", ".join(roles)[:1024],
            inline=False,
        )
        e.set_footer(
            text=f"{guild.name} • Kick Log",
            icon_url=mod.display_avatar.url if mod else None,
        )
        await ui.animate_message(
            channel,
            final=e,
            text="Üye atılıyor",
            emoji_="👢",
            color="warn",
            detail=f"{member.display_name} • {member.id}",
            steps=5,
            delay=0.15,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not before.guild:
            return
        if before.roles != after.roles:
            await self._log_role_change(before, after)
        elif before.display_name != after.display_name:
            await self._log(
                before.guild,
                "🏷️ Başlık Değişimi",
                f"{after.mention}\n**Önce:** {before.display_name}\n**Sonra:** {after.display_name}",
                discord.Color.purple(),
            )

    async def _role_log_channel(self, guild):
        ch = await self._cfg_channel(guild, "role_channel_id")
        if ch:
            return ch
        ch_id = await database.get_setting(guild.id, "role_log_channel", None)
        if ch_id:
            return guild.get_channel(int(ch_id))
        return await self._log_channel(guild)

    async def _role_actor(self, member):
        try:
            async for entry in member.guild.audit_logs(limit=8, action=AuditLogAction.member_role_update):
                if entry.target and entry.target.id == member.id:
                    return entry.user, entry.created_at
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None, None

    async def _log_role_change(self, before, after):
        guild = after.guild
        tag_role_id = database.load_config().get("tag_log", {}).get("tag_role_id")
        added = [r for r in after.roles if r not in before.roles and not r.is_default() and (not tag_role_id or r.id != int(tag_role_id))]
        removed = [r for r in before.roles if r not in after.roles and not r.is_default() and (not tag_role_id or r.id != int(tag_role_id))]
        if not added and not removed:
            return
        actor, acted_at = await self._role_actor(after)
        channel = await self._role_log_channel(guild)
        if not channel:
            return
        for role in added:
            await self._post_role_log(channel, after, role, "verildi", actor, acted_at)
        for role in removed:
            await self._post_role_log(channel, after, role, "alındı", actor, acted_at)

    async def _post_role_log(self, channel, member, role, action, actor, acted_at):
        given = action == "verildi"
        when = acted_at or datetime.datetime.now(datetime.timezone.utc)
        ts = int(when.timestamp())
        e = discord.Embed(
            title=f"{'✅' if given else '❌'} Rol {'Verildi' if given else 'Alındı'}",
            color=discord.Color.green() if given else discord.Color.red(),
            timestamp=when,
        )
        e.add_field(name="👤 Üye", value=member.mention, inline=True)
        e.add_field(name="🎭 Rol", value=role.mention, inline=True)
        e.add_field(name="🛠️ Yetkili", value=actor.mention if actor else "Bilinmiyor", inline=True)
        e.add_field(name="🕐 Tarih & Saat", value=f"<t:{ts}:F>\n`{when.strftime('%d.%m.%Y %H:%M:%S')}`", inline=False)
        if actor and not actor.bot:
            e.set_author(name=actor.display_name, icon_url=actor.display_avatar.url)
        e.set_footer(text=f"{channel.guild.name if channel.guild else ''} • Rol Log")
        await ui.animate_message(
            channel,
            final=e,
            text=f"Rol {action}",
            emoji_="✅" if given else "❌",
            color="success" if given else "error",
            detail=role.name,
            steps=5,
            delay=0.15,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild or member.bot:
            return
        if before.channel and not after.channel:
            await self._log_to(
                await self._voice_log_channel(member.guild),
                member.guild,
                "🎤 Ses Ayrıldı",
                f"{member.mention} **{before.channel.name}** odasından çıktı.",
                discord.Color.red(),
            )
        elif not before.channel and after.channel:
            await self._log_to(
                await self._voice_log_channel(member.guild),
                member.guild,
                "🎤 Sese Katıldı",
                f"{member.mention} **{after.channel.name}** odasına girdi.",
                discord.Color.green(),
            )
        elif before.channel and after.channel and before.channel.id != after.channel.id:
            await self._log_to(
                await self._voice_log_channel(member.guild),
                member.guild,
                "🔄 Ses Odası Değişti",
                f"{member.mention}: **{before.channel.name}** → **{after.channel.name}**",
                discord.Color.orange(),
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self._log_to(
            await self._punish_log_channel(guild),
            guild,
            "🔨 Üye Banlandı",
            f"{user.mention} ({user}) sunucudan banlandı.",
            discord.Color.red(),
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self._log_to(
            await self._punish_log_channel(guild),
            guild,
            "🔓 Ban Kaldırıldı",
            f"{user.mention} ({user}) banı kaldırıldı.",
            discord.Color.green(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not channel.guild:
            return
        await self._log(channel.guild, "📁 Kanal Oluşturuldu", f"**{channel.name}** ({channel.mention}) kanalı oluşturuldu.", discord.Color.green())

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not channel.guild:
            return
        await self._log(channel.guild, "🗑️ Kanal Silindi", f"**{channel.name}** kanalı silindi.", discord.Color.red())

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self._log(role.guild, "🆕 Rol Oluşturuldu", f"**{role.name}** ({role.mention}) rolü oluşturuldu.", discord.Color.green())

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self._log(role.guild, "🗑️ Rol Silindi", f"**{role.name}** rolü silindi.", discord.Color.red())

    @app_commands.command(name="logkanal", description="Log kanalını ayarlar (kanala bot mesaj gönderebilmelidir)")
    @app_commands.checks.has_permissions(administrator=True)
    async def logkanal(self, interaction: discord.Interaction, kanal: discord.TextChannel):
        await database.set_setting(interaction.guild_id, "log_channel", kanal.id)
        e = ui.embed(
            "Log Kanalı",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="📝",
        )
        e.add_field(name="Kanal", value=kanal.mention, inline=True)
        e.add_field(name="Durum", value="✅ Aktif", inline=True)
        await ui.animate(interaction, final=e, text="Kaydediliyor", emoji_="📝", color="success", steps=4, delay=0.14)

    @app_commands.command(name="snipe", description="Kanaldaki son silinen mesajı gösterir")
    async def snipe(self, interaction: discord.Interaction):
        data = self.snipes.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message(
                embed=ui.alert("error", "Bu kanalda silinen mesaj yok.", interaction=interaction),
                ephemeral=True,
            )
            return
        e = ui.embed(
            "Snipe",
            description=data["content"] or "(medya/boş mesaj)",
            color="info",
            interaction=interaction,
            timestamp=True,
            emoji_="🎯",
        )
        e.set_author(name=data["author"].display_name, icon_url=data["author"].display_avatar.url)
        e.set_footer(text=f"{interaction.guild.name if interaction.guild else ''} • 10 saniye içinde kaybolur")
        await ui.animate(interaction, final=e, text="Snipe bulunuyor", emoji_="🎯", color="info", steps=4, delay=0.14)


async def setup(bot):
    await bot.add_cog(Logging(bot))
