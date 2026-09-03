import datetime
import json
import os

import discord
from discord import app_commands
from discord.ext import commands

import database
from utils import ui


TAG_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tag_state.json")


def _load_tag_state():
    if os.path.exists(TAG_STATE_FILE):
        with open(TAG_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_tag_state(state):
    os.makedirs(os.path.dirname(TAG_STATE_FILE), exist_ok=True)
    with open(TAG_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


class TagLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tag_state = _load_tag_state()
        self._ready_synced = False
        print(f"[TagLog] Yüklendi. Tag: {self._tag()}, Guild ID: {self._guild_id()}, Rol: {self._role_id()}, Kanal: {self._channel_id()}")

    def _cfg(self):
        cfg = database.load_config()
        return cfg.get("tag_log", {})

    def _tag(self):
        return self._cfg().get("tag", "IMP")

    def _role_id(self):
        return self._cfg().get("tag_role_id")

    def _channel_id(self):
        return self._cfg().get("log_channel_id")

    def _enabled(self):
        return self._cfg().get("enabled", False)

    def _guild_id(self):
        cfg = database.load_config()
        return cfg.get("guild_id")

    def _has_our_tag(self, member):
        pg = getattr(member, "primary_guild", None)
        if pg is None:
            return False
        if not pg.identity_enabled:
            return False
        if pg.id is None:
            return False
        our_guild_id = self._guild_id()
        if not our_guild_id:
            return False
        return int(pg.id) == int(our_guild_id)

    def _had_tag(self, member_id):
        return str(member_id) in self.tag_state

    def _set_tag_state(self, member_id, has_tag: bool):
        if has_tag:
            self.tag_state[str(member_id)] = True
        else:
            self.tag_state.pop(str(member_id), None)
        _save_tag_state(self.tag_state)

    def _log_channel(self, guild):
        ch_id = self._channel_id()
        if ch_id:
            return guild.get_channel(int(ch_id))
        return None

    def _format_duration(self, seconds):
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

    def _get_tag_text(self, member):
        pg = getattr(member, "primary_guild", None)
        if pg and pg.tag:
            return pg.tag
        return self._tag()

    async def _build_tag_add_embed(self, member, actor, timestamp):
        guild = member.guild
        tag = self._get_tag_text(member)
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        ts = int(now.timestamp())

        e = discord.Embed(
            title="✨ Tagımızı Aldı!",
            description=(
                f"👤 {member.mention} (**{member}**) sunucu tagımızı aldı!\n\n"
                f"🎭 **Kendisine tag rolü verildi.** Aramıza hoş geldin!\n"
                f"🎉 Tagımızı Aldı!"
            ),
            color=discord.Color(0x2ECC71),
            timestamp=now,
        )
        e.set_author(
            name=f"{member.display_name} • {guild.name}",
            icon_url=member.display_avatar.url,
        )
        e.set_thumbnail(url=member.display_avatar.url)

        e.add_field(name="👤 Üye", value=member.mention, inline=True)
        e.add_field(name="🆔 Kullanıcı ID", value=f"`{member.id}`", inline=True)
        e.add_field(name="🏷️ Tag", value=f"`{tag}`", inline=True)

        role = guild.get_role(int(self._role_id())) if self._role_id() else None
        e.add_field(
            name="🎭 Verilen Rol",
            value=role.mention if role else "Rol bulunamadı",
            inline=True,
        )

        if actor and actor.id != member.id:
            e.add_field(name="🛠️ İşlemi Yapan", value=actor.mention, inline=True)
        else:
            e.add_field(name="🛠️ İşlemi Yapan", value="Kendisi", inline=True)

        if member.joined_at:
            stay = self._format_duration((now - member.joined_at).total_seconds())
            e.add_field(
                name="📅 Sunucuda Geçirilen Süre",
                value=stay,
                inline=True,
            )

        if member.created_at:
            e.add_field(
                name="📅 Hesap Açılışı",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )

        roles = [r for r in member.roles if not r.is_default()]
        e.add_field(
            name=f"🎭 Rolleri ({len(roles)})",
            value=", ".join(r.mention for r in roles)[:1024] or "(rolü yok)",
            inline=False,
        )

        e.add_field(name="🕐 Tarih & Saat", value=f"<t:{ts}:F>", inline=True)
        e.set_footer(
            text=f"{guild.name} • Tag Log",
            icon_url=guild.icon.url if guild.icon else None,
        )
        ui.apply_animated(e, guild)
        return e

    async def _build_tag_remove_embed(self, member, actor, timestamp):
        guild = member.guild
        tag = self._tag()
        now = timestamp or datetime.datetime.now(datetime.timezone.utc)
        ts = int(now.timestamp())

        e = discord.Embed(
            title="😢 Tagımızı Bıraktı!",
            description=(
                f"👤 {member.mention} (**{member}**) sunucu tagımızı bıraktı.\n\n"
                f"🎭 **Kendisinden tag rolü alındı.** Umarız tekrar aramıza katılırsın.\n"
                f"😢 Tagımızı Bıraktı!"
            ),
            color=discord.Color(0xE74C3C),
            timestamp=now,
        )
        e.set_author(
            name=f"{member.display_name} • {guild.name}",
            icon_url=member.display_avatar.url,
        )
        e.set_thumbnail(url=member.display_avatar.url)

        e.add_field(name="👤 Üye", value=member.mention, inline=True)
        e.add_field(name="🆔 Kullanıcı ID", value=f"`{member.id}`", inline=True)
        e.add_field(name="🏷️ Tag", value=f"`{tag}`", inline=True)

        role = guild.get_role(int(self._role_id())) if self._role_id() else None
        e.add_field(
            name="🎭 Alınan Rol",
            value=role.mention if role else "Rol bulunamadı",
            inline=True,
        )

        if actor and actor.id != member.id:
            e.add_field(name="🛠️ İşlemi Yapan", value=actor.mention, inline=True)
        else:
            e.add_field(name="🛠️ İşlemi Yapan", value="Kendisi", inline=True)

        if member.joined_at:
            stay = self._format_duration((now - member.joined_at).total_seconds())
            e.add_field(
                name="📅 Sunucuda Geçirilen Süre",
                value=stay,
                inline=True,
            )

        if member.created_at:
            e.add_field(
                name="📅 Hesap Açılışı",
                value=f"<t:{int(member.created_at.timestamp())}:R>",
                inline=True,
            )

        roles = [r for r in member.roles if not r.is_default()]
        e.add_field(
            name=f"🎭 Rolleri ({len(roles)})",
            value=", ".join(r.mention for r in roles)[:1024] or "(rolü yok)",
            inline=False,
        )

        e.add_field(name="🕐 Tarih & Saat", value=f"<t:{ts}:F>", inline=True)
        e.set_footer(
            text=f"{guild.name} • Tag Log",
            icon_url=guild.icon.url if guild.icon else None,
        )
        ui.apply_animated(e, guild)
        return e

    async def _give_tag_role(self, member, reason="Tag aldı"):
        role_id = self._role_id()
        if not role_id:
            return False
        role = member.guild.get_role(int(role_id))
        if not role:
            return False
        if role in member.roles:
            return True
        try:
            await member.add_roles(role, reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _remove_tag_role(self, member, reason="Tag bıraktı"):
        role_id = self._role_id()
        if not role_id:
            return False
        role = member.guild.get_role(int(role_id))
        if not role:
            return False
        if role not in member.roles:
            return True
        try:
            await member.remove_roles(role, reason=reason)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready_synced:
            return
        self._ready_synced = True
        print("[TagLog] Bot başladı, tag senkronizasyonu kontrol ediliyor...")

        guild_id = self._guild_id()
        if not guild_id:
            return
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return

        channel = self._log_channel(guild)
        role = guild.get_role(int(self._role_id())) if self._role_id() else None

        current_tagged = {str(m.id) for m in guild.members if not m.bot and self._has_our_tag(m)}
        saved_tagged = set(self.tag_state.keys())

        for member_id in current_tagged - saved_tagged:
            member = guild.get_member(int(member_id))
            if not member:
                continue
            await self._handle_tag_added(member)
            print(f"[TagLog] Başlangıç senkronu: {member} tag aldı (rol verildi + log gönderildi)")

        for member_id in saved_tagged - current_tagged:
            member = guild.get_member(int(member_id))
            if not member:
                self._set_tag_state(member_id, False)
                continue
            await self._handle_tag_removed(member)
            print(f"[TagLog] Başlangıç senkronu: {member} tag bıraktı (rol alındı + log gönderildi)")

        print(f"[TagLog] Senkronizasyon tamamlandı. Tagı olan: {len(current_tagged)}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not self._enabled() or not before.guild:
            return
        if before.bot:
            return

        had_tag = self._had_tag(before.id)
        has_tag = self._has_our_tag(after)

        print(f"[TagLog] on_member_update: {after.display_name} ({after.id}) | had_tag={had_tag}, has_tag={has_tag}")

        if had_tag and not has_tag:
            await self._handle_tag_removed(after)
        elif not had_tag and has_tag:
            await self._handle_tag_added(after)

    async def _handle_tag_added(self, member):
        self._set_tag_state(member.id, True)
        await self._give_tag_role(member, reason="Tag aldı - otomatik")

        channel = self._log_channel(member.guild)
        if not channel:
            return

        embed = await self._build_tag_add_embed(member, None, None)
        try:
            await ui.animate_message(
                channel,
                final=embed,
                text="Tag alındı",
                emoji_="✨",
                color="success",
                detail=f"{member.display_name} • {member.id}",
                steps=5,
                delay=0.15,
            )
        except discord.Forbidden:
            pass

    async def _handle_tag_removed(self, member):
        self._set_tag_state(member.id, False)
        await self._remove_tag_role(member, reason="Tag bıraktı - otomatik")

        channel = self._log_channel(member.guild)
        if not channel:
            return

        embed = await self._build_tag_remove_embed(member, None, None)
        try:
            await ui.animate_message(
                channel,
                final=embed,
                text="Tag bırakıldı",
                emoji_="😢",
                color="error",
                detail=f"{member.display_name} • {member.id}",
                steps=5,
                delay=0.15,
            )
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not self._enabled() or not member.guild or member.bot:
            return

        has_tag = self._has_our_tag(member)
        had_tag = self._had_tag(member.id)

        if has_tag and not had_tag:
            await self._handle_tag_added(member)
        elif not has_tag and had_tag:
            self._set_tag_state(member.id, False)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if not self._enabled() or not member.guild or member.bot:
            return
        if self._had_tag(member.id):
            self._set_tag_state(member.id, False)

    @app_commands.command(name="tag", description="Tagı olan tüm üyeleri bulur, rol verir ve log kanalına bildirir")
    @app_commands.checks.has_permissions(administrator=True)
    async def tag(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        tagged = [m for m in guild.members if not m.bot and self._has_our_tag(m)]
        channel = self._log_channel(guild)
        role = guild.get_role(int(self._role_id())) if self._role_id() else None
        now = datetime.datetime.now(datetime.timezone.utc)

        if not tagged:
            await interaction.followup.send(f"Sunucuda `{self._tag()}` etiketini kullanan kimse bulunamadı.")
            return

        role_given = 0
        for member in tagged:
            self._set_tag_state(member.id, True)
            if role and role not in member.roles:
                await self._give_tag_role(member, reason="Tag tarama - otomatik")
                role_given += 1

            embed = await self._build_tag_add_embed(member, None, None)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

        await interaction.followup.send(
            f"**{len(tagged)}** kişi bulundu. **{role_given}** kişiye rol verildi. Log kanalına {len(tagged)} mesaj gönderildi."
        )


async def setup(bot):
    await bot.add_cog(TagLog(bot))
