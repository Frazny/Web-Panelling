import time
from collections import defaultdict, deque

import discord
from discord import AuditLogAction
from discord.ext import commands

import database
from utils import ui
from utils.checks import has_dangerous_permissions, is_blacklisted, is_owner, is_whitelisted

DESTRUCTIVE = (AuditLogAction.kick, AuditLogAction.ban, AuditLogAction.unban)


def _serialize_overwrite(target, overwrite):
    allow, deny = overwrite.pair()
    is_role = isinstance(target, discord.Role) or hasattr(target, "is_default")
    return {
        "target_id": target.id,
        "type": 0 if is_role else 1,
        "allow": allow.value,
        "deny": deny.value,
    }


def _deserialize_overwrites(guild, data):
    overwrites = {}
    for item in data:
        target = guild.get_role(item["target_id"])
        if target is None and item["type"] == 1:
            target = guild.get_member(item["target_id"])
        if target is None:
            continue
        allow = discord.Permissions(item["allow"])
        deny = discord.Permissions(item["deny"])
        overwrites[target] = discord.PermissionOverwrite.from_pair(allow, deny)
    return overwrites


def _serialize_channel(ch):
    return {
        "id": ch.id,
        "name": ch.name,
        "type": ch.type.value,
        "category_id": ch.category_id,
        "position": ch.position,
        "topic": getattr(ch, "topic", None),
        "nsfw": getattr(ch, "nsfw", False),
        "slowmode_delay": getattr(ch, "slowmode_delay", 0),
        "overwrites": [_serialize_overwrite(t, o) for t, o in ch.overwrites.items()],
    }


def _serialize_role(role):
    return {
        "id": role.id,
        "name": role.name,
        "color": role.color.value,
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "permissions": role.permissions.value,
        "position": role.position,
    }


class Guard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.nuke_window = defaultdict(deque)
        self.locked = set()

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
        return database.guild_config(guild_id)

    async def _log_channel(self, guild):
        cfg = self._cfg(guild.id)
        ch_id = cfg.get("guard_log_channel", 0)
        if not ch_id:
            ch_id = int(await database.get_setting(guild.id, "guard_log_channel", 0))
        return guild.get_channel(ch_id)

    async def _log(self, guild, title, description, color=discord.Color.blue(), fields=None):
        channel = await self._log_channel(guild)
        if channel is None:
            return
        embed = discord.Embed(
            title=title, description=description, color=color, timestamp=discord.utils.utcnow()
        )
        for name, value, inline in fields or []:
            embed.add_field(name=name, value=value, inline=inline)
        ui.apply_animated(embed, guild)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _audit_actor(self, guild, action, **kwargs):
        target = kwargs.pop("target", None)
        limit = 20 if target is not None else 5
        try:
            async for entry in guild.audit_logs(limit=limit, action=action, **kwargs):
                if target is not None:
                    t = entry.target
                    if t is None or getattr(t, "id", None) != getattr(target, "id", None):
                        continue
                return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    async def _is_trusted(self, guild, actor):
        if actor is None:
            return False
        if await is_blacklisted(guild.id, actor.id):
            return False
        if actor.id == self.bot.user.id:
            return True
        if getattr(guild, "owner_id", None) == actor.id:
            return True
        member = guild.get_member(actor.id)
        if member is not None and member.guild_permissions.administrator:
            return True
        return await is_whitelisted(guild.id, actor.id)

    async def _snapshot_guild(self, guild):
        for channel in guild.channels:
            await database.save_channel_snapshot(guild.id, channel.id, _serialize_channel(channel))
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            await database.save_role_snapshot(guild.id, role.id, _serialize_role(role))

    async def _restore_channels(self, guild, snapshots):
        restored = 0
        existing = {c.id: c for c in guild.channels}
        for ch_id, data in snapshots.items():
            if ch_id in existing:
                continue
            category = guild.get_channel(data.get("category_id")) if data.get("category_id") else None
            overwrites = _deserialize_overwrites(guild, data.get("overwrites", []))
            try:
                ch_type = discord.ChannelType(data["type"])
                position = data.get("position", 0)
                if ch_type == discord.ChannelType.text:
                    await guild.create_text_channel(
                        data["name"], category=category, position=position,
                        topic=data.get("topic"), nsfw=data.get("nsfw", False),
                        slowmode_delay=data.get("slowmode_delay", 0),
                        overwrites=overwrites or None,
                    )
                elif ch_type == discord.ChannelType.voice:
                    await guild.create_voice_channel(
                        data["name"], category=category, position=position, overwrites=overwrites or None
                    )
                elif ch_type == discord.ChannelType.category:
                    await guild.create_category(data["name"], overwrites=overwrites or None)
                else:
                    continue
                restored += 1
            except discord.Forbidden:
                pass
        return restored

    async def _restore_roles(self, guild, snapshots):
        restored = 0
        existing = {r.id: r for r in guild.roles}
        for role_id, data in snapshots.items():
            if role_id in existing:
                continue
            try:
                new_role = await guild.create_role(
                    name=data["name"],
                    color=discord.Color(data.get("color", 0)),
                    hoist=data.get("hoist", False),
                    mentionable=data.get("mentionable", False),
                    permissions=discord.Permissions(data.get("permissions", 0)),
                )
                position = data.get("position", 1)
                if position > 1:
                    await new_role.edit(position=min(position, len(guild.roles) - 1))
                restored += 1
            except discord.Forbidden:
                pass
        return restored

    async def _unban_recent(self, guild, window):
        unbanned = 0
        cfg = self._cfg(guild.id).get("anti_nuke", {})
        try:
            async for entry in guild.audit_logs(limit=20, action=AuditLogAction.ban):
                if not entry.created_at:
                    continue
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > window:
                    break
                actor = entry.user
                if actor and await self._is_trusted(guild, actor):
                    continue
                if entry.target and isinstance(entry.target, discord.Object):
                    try:
                        await guild.unban(entry.target, reason="[Anti-Nuke] Yetkisiz ban geri alındı")
                        unbanned += 1
                    except discord.HTTPException:
                        pass
        except (discord.Forbidden, discord.HTTPException):
            pass
        return unbanned

    async def _track_nuke(self, guild):
        cfg = self._cfg(guild.id)
        anti = cfg.get("anti_nuke", {})
        if not anti.get("enabled", True):
            return
        if guild.id in self.locked:
            return
        threshold = anti.get("threshold", 5)
        window = anti.get("window_seconds", 10)
        now = time.time()
        events = self.nuke_window[guild.id]
        events.append(now)
        while events and events[0] <= now - window:
            events.popleft()
        if len(events) >= threshold:
            await self._lockdown(guild, anti)

    async def _lockdown(self, guild, anti):
        if guild.id in self.locked:
            return
        self.locked.add(guild.id)
        self.nuke_window[guild.id].clear()
        await self._log(
            guild,
            "NUKE SALDIRISI ENGELLENDİ",
            "Yıkıcı işlem hızı eşiğin üzerinde tespit edildi. Sunucu kilitlendi ve geri yükleme başlatıldı.",
            color=discord.Color.red(),
            fields=[("Durum", "Kilitli - /guard unlock ile açabilirsin", False)],
        )
        snapshots = await database.get_channel_snapshots(guild.id)
        restored = await self._restore_channels(guild, snapshots)
        role_snapshots = await database.get_role_snapshots(guild.id)
        restored_roles = await self._restore_roles(guild, role_snapshots)
        unbanned = 0
        if anti.get("auto_unban", True):
            unbanned = await self._unban_recent(guild, anti.get("window_seconds", 10))
        await self._log(
            guild,
            "Geri Yükleme Tamamlandı",
            f"Kanal geri yüklendi: **{restored}**\nRol geri yüklendi: **{restored_roles}**\nBan geri alındı: **{unbanned}**",
            color=discord.Color.green(),
        )

    async def _strip_attacker(self, guild, actor):
        """Saldırgana yaptırım uygular. Audit log'dan gelen actor bir ``User``
        olabilir, bu yüzden önce sunucudaki gerçek ``Member``'ı çözeriz."""
        if actor is None:
            return
        member = guild.get_member(actor.id)
        if member is None:
            return  # saldırgan artık sunucuda değil
        cfg = self._cfg(guild.id)
        if cfg.get("anti_nuke", {}).get("ban_attacker", False):
            try:
                await member.ban(reason="[Anti-Nuke] Saldırgan")
                return
            except discord.Forbidden:
                pass
        to_remove = []
        for role in member.roles:
            if role.is_default() or role.managed:
                continue
            if has_dangerous_permissions(role.permissions):
                to_remove.append(role)
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason="[Anti-Nuke] Tehlikeli roller kaldırıldı")
            except discord.Forbidden:
                pass

    async def _snapshot_delete_is_trusted(self, guild, action):
        """Silme işlemini yapan kişi whitelist'teyse True döner.

        Nuke tespitini bozmamak için snapshot ancak güvenilir bir aktör
        kanal/rol silerse silinir. Aksi halde yedek kalır ve anti-nuke
        geri yüklemesi silinen kanalı/rolü geri getirebilir.

        Bilinen sınırlama: audit log'a erişilemiyorsa (Forbidden) veya
        kayıt bulunamazsa ``False`` döner — yani snapshot her ihtimalde
        korunur. Bu, güvenli (anti-nuke) yönüne öncelik verir; whitelist'li
        bir moderatörün meşru silmesi de sonraki bir geri yüklemede
        dirilebilir."""
        entry = await self._audit_actor(guild, action)
        actor = entry.user if entry else None
        if actor is not None:
            return await self._is_trusted(guild, actor)
        return False

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        if await self._snapshot_delete_is_trusted(guild, AuditLogAction.channel_delete):
            await database.delete_channel_snapshot(guild.id, channel.id)
        await self._log(guild, "Kanal Silindi", f"{channel.name} silindi.", color=discord.Color.orange())
        await self._track_nuke(guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        guild = role.guild
        if await self._snapshot_delete_is_trusted(guild, AuditLogAction.role_delete):
            await database.delete_role_snapshot(guild.id, role.id)
        await self._log(guild, "Rol Silindi", f"{role.name} silindi.", color=discord.Color.orange())
        await self._track_nuke(guild)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await database.save_channel_snapshot(channel.guild.id, channel.id, _serialize_channel(channel))

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        if role.is_default() or role.managed:
            return
        await database.save_role_snapshot(role.guild.id, role.id, _serialize_role(role))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.overwrites == after.overwrites:
            return
        entry = await self._audit_actor(before.guild, AuditLogAction.channel_update)
        actor = entry.user if entry else None
        if actor and await self._is_trusted(before.guild, actor):
            await database.save_channel_snapshot(before.guild.id, after.id, _serialize_channel(after))
            return
        for target, ov in after.overwrites.items():
            if not has_dangerous_permissions(ov.allow):
                continue
            if actor is not None:
                try:
                    await after.edit(overwrites=before.overwrites, reason="[Guard] Yetki yükseltme engellendi")
                except discord.Forbidden:
                    pass
            await self._log(
                before.guild,
                "Yetki Yükseltme Engellendi",
                f"{target} için {after.name} kanalında tehlikeli izin verilmeye çalışıldı.",
                color=discord.Color.red(),
                fields=[("Saldırgan", actor.mention if actor else "Bilinmiyor", False)],
            )
            return

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.permissions == after.permissions:
            return
        gained = after.permissions.value & ~before.permissions.value
        if not has_dangerous_permissions(discord.Permissions(gained)):
            return
        if await database.is_protected_role(after.guild.id, after.id):
            return
        entry = await self._audit_actor(after.guild, AuditLogAction.role_update)
        actor = entry.user if entry else None
        if actor and await self._is_trusted(after.guild, actor):
            await database.save_role_snapshot(after.guild.id, after.id, _serialize_role(after))
            return
        try:
            await after.edit(permissions=before.permissions, reason="[Guard] Tehlikeli izin geri alındı")
        except discord.Forbidden:
            pass
        await self._log(
            after.guild,
            "Rol Yetki Yükseltmesi Engellendi",
            f"{after.mention} rolüne tehlikeli izin verilmeye çalışıldı.",
            color=discord.Color.red(),
            fields=[("Saldırgan", actor.mention if actor else "Bilinmiyor", False)],
        )

    def _banned_roles_for(self, guild, member_id):
        bans = self._cfg(guild.id).get("role_bans") or {}
        return {int(r) for r in bans.get(str(member_id), [])}

    async def _enforce_role_bans(self, guild):
        bans = self._cfg(guild.id).get("role_bans") or {}
        for member_id, role_ids in bans.items():
            member = guild.get_member(int(member_id))
            if member is None:
                try:
                    member = await guild.fetch_member(int(member_id))
                except discord.HTTPException:
                    continue
            to_remove = [r for r in member.roles if r.id in role_ids]
            if not to_remove:
                continue
            try:
                await member.remove_roles(*to_remove, reason="[Guard] Yasaklı rol temizlendi")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        added = [r for r in after.roles if r not in before.roles]
        if not added:
            return
        banned_ids = self._banned_roles_for(after.guild, after.id)
        for role in added:
            if role.id in banned_ids:
                try:
                    await after.remove_roles(role, reason="[Guard] Yasaklı rol eklendi, kaldırıldı")
                except discord.HTTPException:
                    pass
                await self._log(
                    after.guild,
                    "Yasaklı Rol Engellendi",
                    f"{after.mention} kullanıcısına {role.mention} rolü verilmeye çalışıldı ve geri alındı.",
                    color=discord.Color.red(),
                    fields=[("Kullanıcı", after.mention, False)],
                )
                continue
            if has_dangerous_permissions(role.permissions):
                await self._log(
                    after.guild,
                    "Rol Verildi",
                    f"{after.mention} kullanıcısına {role.mention} rolü verildi.",
                    color=discord.Color.orange(),
                )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        entry = await self._audit_actor(guild, AuditLogAction.ban)
        actor = entry.user if entry else None
        if actor and await self._is_trusted(guild, actor):
            await self._log(guild, "Üye Banlandı", f"{user} banlandı.", color=discord.Color.orange())
            return
        protected = await database.is_protected_member(guild.id, user.id)
        if not protected and user.id != (self._cfg(guild.id).get("owner_id") or 0):
            await self._track_nuke(guild)
            if guild.id not in self.locked:
                try:
                    await guild.unban(user, reason="[Guard] Yetkisiz ban geri alındı")
                except discord.HTTPException:
                    pass
            await self._log(
                guild,
                "Ban Engellendi",
                f"{user} banlanmaya çalışıldı ancak geri alındı.",
                color=discord.Color.red(),
                fields=[("Saldırgan", actor.mention if actor else "Bilinmiyor", False)],
            )
            if actor:
                await self._strip_attacker(guild, actor)
        else:
            await self._log(
                guild,
                "Ban Engellendi",
                f"Korunan üye {user} banlanmaya çalışıldı.",
                color=discord.Color.red(),
                fields=[("Saldırgan", actor.mention if actor else "Bilinmiyor", False)],
            )
            if actor:
                await self._strip_attacker(guild, actor)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        if await database.is_protected_member(guild.id, member.id):
            await self._log(
                guild,
                "Korunan Üye Sunucudan Ayrıldı",
                f"{member} sunucudan çıkarıldı.",
                color=discord.Color.orange(),
            )
        entry = await self._audit_actor(guild, AuditLogAction.kick, target=member)
        if not entry or not entry.user:
            return
        actor = entry.user
        if await self._is_trusted(guild, actor):
            return
        await self._track_nuke(guild)
        await self._log(
            guild,
            "Kick Tespit Edildi",
            f"{member} kicklendi.",
            color=discord.Color.red(),
            fields=[("Saldırgan", actor.mention, False)],
        )
        await self._strip_attacker(guild, actor)

    async def _guard_check(self, interaction):
        if await is_whitelisted(interaction.guild_id, interaction.user.id):
            return True
        await interaction.response.send_message(
            embed=ui.alert("error", "Bu komutu kullanma yetkin yok.", interaction=interaction),
            ephemeral=True,
        )
        return False

    async def _ensure_owner_role(self, guild):
        """Kurucu rolü varsa onu yönetir (izin + konum + üye ataması).

        Rolü OTOMATİK OLUŞTURMAZ: kullanıcı Kurucu rolünü silmek istediğinde
        bot yeniden oluşturmamalıdır. Rol mevcut değilse hiçbir işlem yapılmaz.

        Discord rol hiyerarşisi botun kendi rolünün üstüne rol koymasına
        izin vermediği için bot rolü Kurucu'nun hemen altına indirilir.
        Böylece Kurucu rolüne sahip kullanıcılar botun rolünü de yönetebilir.
        """
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return
        cfg = self._cfg(guild.id)
        name = cfg.get("kurucu_role_name") or "👑 Kurucu"
        users = cfg.get("kurucu_users") or []
        if not users:
            return
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            return
        if not role.permissions.administrator:
            try:
                await role.edit(
                    permissions=discord.Permissions(administrator=True),
                    reason="[Guard] Kurucu rolü güncellendi",
                )
            except discord.Forbidden:
                pass
        if role.position <= me.top_role.position:
            try:
                await role.edit(position=max(me.top_role.position - 1, 1))
            except discord.HTTPException:
                pass
            try:
                await me.top_role.edit(position=max(role.position - 1, 1))
            except discord.HTTPException:
                pass
        for uid in users:
            if uid == self.bot.user.id:
                continue
            member = guild.get_member(uid)
            if member is None:
                continue
            if role in member.roles:
                continue
            try:
                await member.add_roles(role, reason="[Guard] Kurucu rolü atandı")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._snapshot_guild(guild)
            await self._ensure_owner_role(guild)
            await self._enforce_role_bans(guild)
        print("[Guard] Güvenlik başlatıldı.")

    @discord.app_commands.command(name="guard", description="Guard yönetim komutları")
    @discord.app_commands.describe(action="lockdown, unlock veya restore")
    async def guard(self, interaction: discord.Interaction, action: str):
        if not await self._guard_check(interaction):
            return
        action = action.lower()
        if action == "lockdown":
            self.locked.add(interaction.guild_id)
            self.nuke_window[interaction.guild_id].clear()
            e = ui.embed(
                "Sunucu Kilitlendi",
                "Guard artık tüm yıkıcı işlemleri engelliyor. Açmak için `/guard unlock` kullan.",
                color="guard",
                interaction=interaction,
                timestamp=True,
                emoji_="🔒",
            )
            await ui.animate(interaction, final=e, text="Kilit uygulanıyor", emoji_="🔒", color="guard", steps=4, delay=0.14)
        elif action == "unlock":
            self.locked.discard(interaction.guild_id)
            e = ui.embed(
                "Sunucu Kilidi Açıldı",
                "Guard koruması normal seviyeye döndü.",
                color="success",
                interaction=interaction,
                timestamp=True,
                emoji_="🔓",
            )
            await ui.animate(interaction, final=e, text="Kilit açılıyor", emoji_="🔓", color="success", steps=4, delay=0.14)
        elif action == "restore":
            edit = await ui.animate(
                interaction,
                defer=True,
                text="Geri yükleme başlatılıyor",
                emoji_="♻️",
                color="guard",
                steps=6,
                delay=0.2,
            )
            snapshots = await database.get_channel_snapshots(interaction.guild_id)
            restored = await self._restore_channels(interaction.guild, snapshots)
            role_snapshots = await database.get_role_snapshots(interaction.guild_id)
            restored_roles = await self._restore_roles(interaction.guild, role_snapshots)
            e = ui.embed(
                "Geri Yükleme Tamamlandı",
                description=None,
                color="success",
                interaction=interaction,
                timestamp=True,
                emoji_="♻️",
            )
            e.add_field(name="Kanal", value=f"**{restored}** geri yüklendi", inline=True)
            e.add_field(name="Rol", value=f"**{restored_roles}** geri yüklendi", inline=True)
            await edit(embed=ui.apply_animated(e, interaction.guild), content=None)
        else:
            await interaction.response.send_message(
                embed=ui.alert("warn", "Geçerli eylemler: lockdown, unlock, restore", interaction=interaction),
                ephemeral=True,
            )

    @discord.app_commands.command(name="snapshot", description="Mevcut kanal ve rolleri yedeğe alır")
    async def snapshot(self, interaction: discord.Interaction):
        if not await self._guard_check(interaction):
            return
        edit = await ui.animate(
            interaction,
            defer=True,
            text="Yedek alınıyor",
            emoji_="💾",
            color="guard",
            steps=5,
            delay=0.16,
        )
        await self._snapshot_guild(interaction.guild)
        e = ui.embed(
            "Yedek Alındı",
            f"Tüm kanal ve roller yedeğe alındı.",
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="💾",
        )
        e.add_field(name="Kanal", value=f"**{len(interaction.guild.channels)}**", inline=True)
        e.add_field(name="Rol", value=f"**{len(interaction.guild.roles)}**", inline=True)
        await edit(embed=ui.apply_animated(e, interaction.guild), content=None)

    @discord.app_commands.command(name="guardlog", description="Guard log kanalını ayarlar")
    async def guardlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._guard_check(interaction):
            return
        await database.set_setting(interaction.guild_id, "guard_log_channel", channel.id)
        e = ui.embed(
            "Guard Log Kanalı",
            description=None,
            color="success",
            interaction=interaction,
            timestamp=True,
            emoji_="🛡️",
        )
        e.add_field(name="Kanal", value=channel.mention, inline=True)
        await ui.animate(interaction, final=e, text="Kaydediliyor", emoji_="🛡️", color="success", steps=4, delay=0.14)

    @discord.app_commands.command(name="wl", description="Whitelist yönetimi: add/remove/list")
    @discord.app_commands.describe(action="add, remove veya list", user="Eklenecek/çıkarılacak üye")
    async def wl(self, interaction: discord.Interaction, action: str, user: discord.User = None):
        if not await self._guard_check(interaction):
            return
        action = action.lower()
        if action == "add":
            if user is None:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Bir üye belirt.", interaction=interaction), ephemeral=True
                )
                return
            await database.add_whitelist(interaction.guild_id, user.id)
            e = ui.embed(
                "Whitelist'e Eklendi",
                description=None,
                color="success",
                interaction=interaction,
                timestamp=True,
                emoji_="✅",
            )
            e.add_field(name="Üye", value=user.mention, inline=True)
            await ui.animate(interaction, final=e, text="Ekleniyor", emoji_="✅", color="success", steps=4, delay=0.14)
        elif action == "remove":
            if user is None:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Bir üye belirt.", interaction=interaction), ephemeral=True
                )
                return
            await database.remove_whitelist(interaction.guild_id, user.id)
            e = ui.embed(
                "Whitelist'ten Çıkarıldı",
                description=None,
                color="warn",
                interaction=interaction,
                timestamp=True,
                emoji_="🗑️",
            )
            e.add_field(name="Üye", value=user.mention, inline=True)
            await ui.animate(interaction, final=e, text="Çıkarılıyor", emoji_="🗑️", color="warn", steps=4, delay=0.14)
        elif action == "list":
            ids = await database.get_whitelist(interaction.guild_id)
            if not ids:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Whitelist boş.", interaction=interaction), ephemeral=True
                )
                return
            names = []
            for uid in ids:
                member = interaction.guild.get_member(uid)
                names.append(member.mention if member else f"Bilinmeyen ({uid})")
            e = ui.embed(
                "Whitelist",
                "**" + ", ".join(names) + "**",
                color="guard",
                interaction=interaction,
                timestamp=True,
                emoji_="🛡️",
            )
            e.add_field(name="Toplam", value=f"**{len(names)}** üye", inline=True)
            await ui.animate(interaction, final=e, text="Liste getiriliyor", emoji_="🛡️", color="guard", steps=4, delay=0.14)
        else:
            await interaction.response.send_message(
                embed=ui.alert("warn", "Geçerli eylemler: add, remove, list", interaction=interaction),
                ephemeral=True,
            )

    @discord.app_commands.command(name="bl", description="Blacklist yönetimi: add/remove/list")
    @discord.app_commands.describe(action="add, remove veya list", user="Eklenecek/çıkarılacak üye")
    async def bl(self, interaction: discord.Interaction, action: str, user: discord.User = None):
        if not await self._guard_check(interaction):
            return
        action = action.lower()
        if action == "add":
            if user is None:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Bir üye belirt.", interaction=interaction), ephemeral=True
                )
                return
            await database.add_blacklist(interaction.guild_id, user.id)
            e = ui.embed(
                "Blacklist'e Eklendi",
                description=None,
                color="success",
                interaction=interaction,
                timestamp=True,
                emoji_="✅",
            )
            e.add_field(name="Üye", value=user.mention, inline=True)
            await ui.animate(interaction, final=e, text="Ekleniyor", emoji_="✅", color="success", steps=4, delay=0.14)
        elif action == "remove":
            if user is None:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Bir üye belirt.", interaction=interaction), ephemeral=True
                )
                return
            await database.remove_blacklist(interaction.guild_id, user.id)
            e = ui.embed(
                "Blacklist'ten Çıkarıldı",
                description=None,
                color="warn",
                interaction=interaction,
                timestamp=True,
                emoji_="🗑️",
            )
            e.add_field(name="Üye", value=user.mention, inline=True)
            await ui.animate(interaction, final=e, text="Çıkarılıyor", emoji_="🗑️", color="warn", steps=4, delay=0.14)
        elif action == "list":
            ids = await database.get_blacklist(interaction.guild_id)
            if not ids:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Blacklist boş.", interaction=interaction), ephemeral=True
                )
                return
            names = []
            for uid in ids:
                member = interaction.guild.get_member(uid)
                names.append(member.mention if member else f"Bilinmeyen ({uid})")
            e = ui.embed(
                "Blacklist",
                "**" + ", ".join(names) + "**",
                color="guard",
                interaction=interaction,
                timestamp=True,
                emoji_="🛡️",
            )
            e.add_field(name="Toplam", value=f"**{len(names)}** üye", inline=True)
            await ui.animate(interaction, final=e, text="Liste getiriliyor", emoji_="🛡️", color="guard", steps=4, delay=0.14)
        else:
            await interaction.response.send_message(
                embed=ui.alert("warn", "Geçerli eylemler: add, remove, list", interaction=interaction),
                ephemeral=True,
            )

    @discord.app_commands.command(name="protect", description="Korunan rol/üye yönetimi")
    @discord.app_commands.describe(
        action="add, remove veya list",
        rol="Korunacak rol (rol eklerken kullan)",
        user="Korunacak üye (üye eklerken kullan)",
    )
    async def protect(
        self,
        interaction: discord.Interaction,
        action: str,
        rol: discord.Role = None,
        user: discord.Member = None,
    ):
        if not await self._guard_check(interaction):
            return
        action = action.lower()
        if action == "add":
            if rol:
                await database.add_protected_role(interaction.guild_id, rol.id)
                e = ui.embed(
                    "Rol Korumaya Alındı",
                    description=None,
                    color="success",
                    interaction=interaction,
                    timestamp=True,
                    emoji_="🛡️",
                )
                e.add_field(name="Rol", value=rol.mention, inline=True)
                await ui.animate(interaction, final=e, text="Korumaya alınıyor", emoji_="🛡️", color="success", steps=4, delay=0.14)
            elif user:
                await database.add_protected_member(interaction.guild_id, user.id)
                e = ui.embed(
                    "Üye Korumaya Alındı",
                    description=None,
                    color="success",
                    interaction=interaction,
                    timestamp=True,
                    emoji_="🛡️",
                )
                e.add_field(name="Üye", value=user.mention, inline=True)
                await ui.animate(interaction, final=e, text="Korumaya alınıyor", emoji_="🛡️", color="success", steps=4, delay=0.14)
            else:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Rol veya üye belirtmelisin.", interaction=interaction),
                    ephemeral=True,
                )
        elif action == "remove":
            if rol:
                await database.remove_protected_role(interaction.guild_id, rol.id)
                e = ui.embed(
                    "Rol Korumadan Çıkarıldı",
                    description=None,
                    color="warn",
                    interaction=interaction,
                    timestamp=True,
                    emoji_="🛡️",
                )
                e.add_field(name="Rol", value=rol.mention, inline=True)
                await ui.animate(interaction, final=e, text="Korumadan çıkarılıyor", emoji_="🛡️", color="warn", steps=4, delay=0.14)
            elif user:
                await database.remove_protected_member(interaction.guild_id, user.id)
                e = ui.embed(
                    "Üye Korumadan Çıkarıldı",
                    description=None,
                    color="warn",
                    interaction=interaction,
                    timestamp=True,
                    emoji_="🛡️",
                )
                e.add_field(name="Üye", value=user.mention, inline=True)
                await ui.animate(interaction, final=e, text="Korumadan çıkarılıyor", emoji_="🛡️", color="warn", steps=4, delay=0.14)
            else:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Rol veya üye belirtmelisin.", interaction=interaction),
                    ephemeral=True,
                )
        elif action == "list":
            roles = await database.get_protected_roles(interaction.guild_id)
            members = await database.get_protected_members(interaction.guild_id)
            parts = []
            role_names = []
            for rid in roles:
                role = interaction.guild.get_role(rid)
                role_names.append(role.mention if role else f"Bilinmeyen ({rid})")
            if role_names:
                parts.append("**Korunan roller:** " + ", ".join(role_names))
            member_names = []
            for uid in members:
                m = interaction.guild.get_member(uid)
                member_names.append(m.mention if m else f"Bilinmeyen ({uid})")
            if member_names:
                parts.append("**Korunan üyeler:** " + ", ".join(member_names))
            if not parts:
                await interaction.response.send_message(
                    embed=ui.alert("warn", "Koruma listesi boş.", interaction=interaction),
                    ephemeral=True,
                )
            else:
                e = ui.embed(
                    "Koruma Listesi",
                    "\n\n".join(parts),
                    color="guard",
                    interaction=interaction,
                    timestamp=True,
                    emoji_="🛡️",
                )
                await ui.animate(interaction, final=e, text="Liste getiriliyor", emoji_="🛡️", color="guard", steps=4, delay=0.14)
        else:
            await interaction.response.send_message(
                embed=ui.alert("warn", "Geçerli eylemler: add, remove, list", interaction=interaction),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(Guard(bot))
