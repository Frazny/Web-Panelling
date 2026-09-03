import discord

from database import load_config


def is_owner(user_id):
    cfg = load_config()
    return user_id == cfg.get("owner_id")


async def is_whitelisted(guild_id, user_id):
    import database

    if is_owner(user_id):
        return True
    if await database.is_whitelisted(guild_id, user_id):
        return True
    return False


async def is_blacklisted(guild_id, user_id):
    import database

    return await database.is_blacklisted(guild_id, user_id)


def has_role(member, role_id):
    if not role_id:
        return False
    return any(r.id == role_id for r in member.roles)


def is_bot_admin(member, cfg):
    admin_role = cfg.get("admin_role_id", 0)
    if admin_role and has_role(member, admin_role):
        return True
    return member.guild_permissions.administrator


DANGEROUS_PERMISSIONS = discord.Permissions(
    discord.Permissions.administrator.flag
    | discord.Permissions.manage_guild.flag
    | discord.Permissions.manage_roles.flag
    | discord.Permissions.manage_channels.flag
    | discord.Permissions.kick_members.flag
    | discord.Permissions.ban_members.flag
    | discord.Permissions.manage_messages.flag
    | discord.Permissions.manage_webhooks.flag
)


def has_dangerous_permissions(permissions):
    return bool(permissions.value & DANGEROUS_PERMISSIONS.value)
