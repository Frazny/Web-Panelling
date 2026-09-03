import asyncio
import logging
import os
import sys
import threading
import traceback

# .env dosyasını yükle (python-dotenv varsa kullan, yoksa manuel oku)
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        # python-dotenv yüklü değilse manuel parse et
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
from utils import ui

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO)

RESTART_FLAG = "restart.flag"
STOP_FLAG = "stop.flag"

ROTATING_STATUSES = [
    (discord.ActivityType.playing, "𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿 𝗕𝘆 𝗙𝗿𝗮𝘇𝗻𝘆"),
    (discord.ActivityType.watching, "𝑰𝑴𝑷"),
    (discord.ActivityType.playing, "𝐂𝐨𝐧𝐭𝐚𝐜𝐭 ; 𝐅𝐫𝐚𝐳𝐧𝐲"),
]
STATUS_INTERVAL = 5

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=database.load_config().get("prefix", "!"),
    intents=intents,
    help_command=None,
    application_id=database.load_config().get("bot_user_id"),
)


async def seed_guard_data():
    cfg = database.load_config()
    guild_ids = [cfg.get("guild_id")]
    guild_ids += [int(gid) for gid in cfg.get("guilds", {})]
    for guild_id in guild_ids:
        if not guild_id:
            continue
        gcfg = database.guild_config(guild_id)
        for uid in gcfg.get("whitelist", []):
            await database.add_whitelist(guild_id, uid)
        for rid in gcfg.get("protected_roles", []):
            await database.add_protected_role(guild_id, rid)
        for uid in gcfg.get("protected_members", []):
            await database.add_protected_member(guild_id, uid)


async def _restore_persistent_views():
    from cogs.rolemenu import RoleMenuView

    for guild in bot.guilds:
        for menu in await database.get_role_menus(guild.id):
            view = RoleMenuView(menu["payload"].get("items", []))
            bot.add_view(view, message_id=menu["message_id"])


async def _sync_commands():
    cfg = database.load_config()
    guild_id = cfg.get("guild_id")

    def _copy(guild):
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)

    # Yapılandırılmış ana guild'e senkronize et. Bot o guild'de değilse
    # 403 dönebilir; on_ready'yi çökertmemesi için hata yakalanır.
    if guild_id:
        guild = discord.Object(id=guild_id)
        _copy(guild)
        try:
            synced = await bot.tree.sync(guild=guild)
            print(f"Sunucu komutları senkronize edildi: {len(synced)} komut")
        except discord.HTTPException as e:
            print(f"Sunucu komutları senkronize edilemedi ({guild_id}): {e}")

    # Botun gerçekten bulunduğu tüm sunuculara da senkronize et; böylece
    # her sunucuda slash komutlar kullanılabilir olur.
    for g in bot.guilds:
        if guild_id and g.id == guild_id:
            continue
        guild = discord.Object(id=g.id)
        _copy(guild)
        try:
            synced = await bot.tree.sync(guild=guild)
            print(f"{g.name} sunucu komutları senkronize edildi: {len(synced)} komut")
        except discord.HTTPException as e:
            print(f"{g.name} senkronize edilemedi: {e}")

    # NOT: Global komut senkronu kasıtlı olarak yapılmıyor. Komutlar hem
    # global hem guild'e kaydedilirse Discord her komutu 2 kez gösterir.
    # Yalnızca guild senkronu kullanılır (yukarıdaki döngü).


async def _status_rotator():
    await bot.wait_until_ready()
    index = 0
    while True:
        if os.path.exists(RESTART_FLAG):
            return
        act_type, text = ROTATING_STATUSES[index % len(ROTATING_STATUSES)]
        try:
            await bot.change_presence(
                status=discord.Status.idle,
                activity=discord.Activity(type=act_type, name=text),
            )
        except ConnectionError:
            # Gateway yeniden bağlanırken transport kapanabilir; sorun değil,
            # bir sonraki turda tekrar denenir. Log spamlamasın diye sessiz geç.
            pass
        except Exception as e:
            print(f"[Durum] değiştirilemedi: {type(e).__name__}: {e}", flush=True)
        index += 1
        await asyncio.sleep(STATUS_INTERVAL)


async def _restart_watcher():
    await bot.wait_until_ready()
    while True:
        if os.path.exists(STOP_FLAG):
            try:
                os.remove(STOP_FLAG)
            except OSError:
                pass
            await bot.change_presence(status=discord.Status.invisible)
            for vc in list(bot.voice_clients):
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            print("Durdurma isteği alındı, çevrimdışı kapatılıyorum.")
            await bot.close()
            return
        if os.path.exists(RESTART_FLAG):
            try:
                os.remove(RESTART_FLAG)
            except OSError:
                pass
            await bot.change_presence(status=discord.Status.invisible)
            for vc in list(bot.voice_clients):
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
            print("Yeniden başlatma isteği alındı, çevrimdışı kapatılıyorum.")
            await bot.close()
            return
        await asyncio.sleep(1)


@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.idle)
    await _sync_commands()
    await _restore_persistent_views()
    print(f"Bot giriş yaptı: {bot.user} (ID: {bot.user.id})")
    print("Sunucular:", [g.name for g in bot.guilds])


@bot.tree.error
async def _tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    traceback.print_exception(type(error), error, error.__traceback__)
    e = ui.alert(
        "error",
        "Komut çalışırken bir hata oluştu. Lütfen `bot_err.log` dosyasını kontrol et veya tekrar dene.",
        interaction=interaction,
    )
    e.add_field(name="Hata", value=f"`{type(error).__name__}`", inline=True)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=e, ephemeral=True)
        else:
            await interaction.response.send_message(embed=e, ephemeral=True)
    except discord.HTTPException:
        pass


def _start_panel():
    """Flask web panelini ayrı bir thread'de başlatır."""
    panel_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel")
    sys.path.insert(0, panel_dir)
    try:
        # Gerekli env değişkenlerini kontrol et
        if not os.environ.get("DISCORD_CLIENT_ID"):
            print("[Panel] DISCORD_CLIENT_ID ayarlanmamış, panel başlatılmıyor.", flush=True)
            return
        import importlib, types
        spec = importlib.util.spec_from_file_location("panel_app", os.path.join(panel_dir, "app.py"))
        panel_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(panel_module)
        port = int(os.environ.get("PANEL_PORT", os.environ.get("PORT", 5000)))
        print(f"[Panel] http://0.0.0.0:{port} adresinde başlatılıyor...", flush=True)
        panel_module.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[Panel] Başlatma hatası: {e}", flush=True)
        traceback.print_exc()


async def main():
    await database.init_db()
    await seed_guard_data()

    # Web panelini arka planda başlat (daemon thread — bot kapanınca o da kapanır)
    panel_thread = threading.Thread(target=_start_panel, name="panel", daemon=True)
    panel_thread.start()

    async with bot:
        await bot.load_extension("cogs.guard")
        await bot.load_extension("cogs.moderation")
        await bot.load_extension("cogs.registration")
        await bot.load_extension("cogs.welcome")
        await bot.load_extension("cogs.levels")
        await bot.load_extension("cogs.invites")
        await bot.load_extension("cogs.tickets")
        await bot.load_extension("cogs.interface")
        await bot.load_extension("cogs.music")
        await bot.load_extension("cogs.economy")
        await bot.load_extension("cogs.logging")
        await bot.load_extension("cogs.utility")
        await bot.load_extension("cogs.rolemenu")
        await bot.load_extension("cogs.social")
        await bot.load_extension("cogs.management")
        await bot.load_extension("cogs.voice_keep")
        await bot.load_extension("cogs.automod")
        await bot.load_extension("cogs.emoji")
        await bot.load_extension("cogs.ai_chat")
        await bot.load_extension("cogs.gender")
        await bot.load_extension("cogs.manifest")
        await bot.load_extension("cogs.taglog")

        asyncio.create_task(_status_rotator())
        asyncio.create_task(_restart_watcher())

        cfg = database.load_config()
        await bot.start(cfg["token"])


if __name__ == "__main__":
    asyncio.run(main())
