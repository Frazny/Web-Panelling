import asyncio

import discord

import database
import main

EXTS = [
    "cogs.guard",
    "cogs.moderation",
    "cogs.registration",
    "cogs.welcome",
    "cogs.levels",
    "cogs.invites",
    "cogs.tickets",
    "cogs.interface",
    "cogs.music",
    "cogs.economy",
    "cogs.logging",
    "cogs.utility",
    "cogs.rolemenu",
    "cogs.social",
    "cogs.management",
    "cogs.automod",
    "cogs.voice_keep",
    "cogs.emoji",
]


async def run():
    await database.init_db()
    bot = main.bot
    for ext in EXTS:
        await bot.load_extension(ext)

    async def on_ready():
        guild_id = database.load_config()["guild_id"]
        guild = discord.Object(id=guild_id)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"GUILD_SENKRON={len(synced)}")
        print("SYNCED=" + ",".join(c.name for c in synced))
        await bot.close()

    bot.add_listener(on_ready, "on_ready")
    await bot.start(database.load_config()["token"])


asyncio.run(run())
