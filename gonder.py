import asyncio

import discord
from discord.ext import commands

import database

CHANNEL_ID = 1413200759893397575
USER_ID = 523542769545773057
MESSAGE = "<@{user}> oruspu anam çay demlemiş benim gibi oruspu evladı varsa buyursun gelsin içsin".format(user=USER_ID)


async def main():
    token = database.load_config()["token"]

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    @bot.event
    async def on_ready():
        try:
            channel = bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
            await channel.send(MESSAGE)
            print("Mesaj gönderildi.")
        except Exception as e:
            print(f"Hata: {e}")
        finally:
            await bot.close()

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
