import asyncio

import discord
from discord.ext import commands

import database

CHANNEL_ID = 1537219053523963904

EMOJI_ROLES = [
    (1537227276851216444, 1537218520599887872),
    (1537227055832502372, 1537218497246142474),
    (1537226722636988536, 1537218373811699712),
    (1537225869767221318, 1537218129808330802),
    (1537224930217824286, 1537218834740678756),
    (1537225622139568150, 1537217824437829652),
]


def _resolve_emoji(guild, emoji_id):
    return guild.get_emoji(emoji_id) or discord.PartialEmoji(name="_", id=emoji_id)


async def main():
    token = database.load_config()["token"]

    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        try:
            channel = bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)
            guild = channel.guild
            desc = []
            for emoji_id, role_id in EMOJI_ROLES:
                role = guild.get_role(role_id)
                name = role.name if role else f"Rol {role_id}"
                desc.append(f"{_resolve_emoji(guild, emoji_id)} **{name}**")
            embed = discord.Embed(
                title="💖 Hangi Manifest Kızısın?",
                description=(
                    "Aşağıdaki tepkilerden birine basarak manifest kızı rolünü seç. "
                    "İlk seçimin kesindir, sonradan başka birini seçemezsin.\n\n"
                    + "\n".join(desc)
                ),
                color=discord.Color(0xE91E63),
            )
            embed.set_footer(text=f"{guild.name} • Manifest Kızı")
            msg = await channel.send(content="Hangi Manifest Kızısın? @everyone", embed=embed)
            for emoji_id, _role_id in EMOJI_ROLES:
                try:
                    await msg.add_reaction(_resolve_emoji(guild, emoji_id))
                except discord.HTTPException as e:
                    print(f"Tepki hatası ({emoji_id}): {e}")
            await database.save_manifest_roles(guild.id, msg.id, EMOJI_ROLES)
            print(f"Panel gönderildi: {msg.jump_url}")
        except Exception as e:
            print(f"Hata: {e}")
        finally:
            await bot.close()

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
