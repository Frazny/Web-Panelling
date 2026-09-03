import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import discord
from discord.ext import commands

import database

CFG = database.load_config()
TOKEN = CFG["token"]
TEST_CHANNEL_ID = 1490389801407348836
OWNER_ID = CFG.get("owner_id")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)


async def main():
    await bot.login(TOKEN)
    conn = asyncio.create_task(bot.connect())
    await bot.wait_until_ready()

    channel = bot.get_channel(TEST_CHANNEL_ID)
    if channel is None:
        print("Kanal bulunamadi")
        await bot.close()
        return
    guild = channel.guild

    if channel.slowmode_delay:
        await channel.edit(slowmode_delay=0)
        print(f"slowmode sifirlandi (onceki {channel.slowmode_delay}s -> 0)")

    targets = set()
    if OWNER_ID:
        m = guild.get_member(OWNER_ID)
        if m:
            targets.add(m.id)
    if guild.owner:
        targets.add(guild.owner.id)
    for uid in targets:
        for claim in ("daily", "weekly", "work"):
            await database.set_cooldown(guild.id, uid, claim, 0)
    print(f"cooldown temizlendi: guild={guild.id} hedefler={list(targets)}")

    await bot.close()
    conn.cancel()


asyncio.run(main())
print("TEMIZLIK OK")
