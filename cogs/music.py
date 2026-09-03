import asyncio
import glob
import logging
import os
import random
import shutil
import time
import uuid

import aiohttp
import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

import database
from utils import ui

logger = logging.getLogger("music")

# 7/24 bağlantıda başarısız denemeler arası kademeli bekleme (saniye).
ALWAYS_RETRY_DELAYS = (15, 15, 60, 60, 60, 300, 300)

# Müzik bittikten sonra 7/24 kanala dönmeden önce beklenen boşta kalma süresi (saniye).
IDLE_RETURN_SECONDS = 300

def _find_ffmpeg():
    """Sistemde kurulu ffmpeg'i bulur (PATH, WinGet veya imageio-ffmpeg yedeği)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    base = os.path.join(local, "Microsoft", "WinGet", "Packages")
    candidates = glob.glob(os.path.join(base, "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe"))
    candidates += glob.glob(os.path.join(base, "Gyan.FFmpeg*", "bin", "ffmpeg.exe"))
    if candidates:
        return sorted(candidates)[-1]
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass
    return "ffmpeg"


FFMPEG = _find_ffmpeg()

TRACK_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tmp")

def _player_clients():
    if os.path.exists("cookies.txt"):
        return ["web", "web_safari", "web_embedded", "tv", "android"]
    return ["android", "tv", "web"]


YDL_BASE = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "extractor_args": {
        "youtube": {"player_client": _player_clients()},
    },
}

if os.path.exists("cookies.txt"):
    YDL_BASE["cookiefile"] = "cookies.txt"


def _fmt(seconds):
    if not seconds:
        return "0:00"
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


class Track:
    __slots__ = ("title", "url", "author", "length", "thumbnail", "stream_url", "local_path")

    def __init__(self, title, url, author, length, thumbnail, stream_url):
        self.title = title
        self.url = url
        self.author = author
        self.length = length
        self.thumbnail = thumbnail
        self.stream_url = stream_url
        self.local_path = None


def _to_track(info):
    stream = (info.get("url") or "").strip()
    if not stream:
        return None
    return Track(
        title=info.get("title") or "Bilinmiyor",
        url=info.get("webpage_url") or info.get("original_url") or "",
        author=info.get("channel") or info.get("uploader") or "Bilinmiyor",
        length=info.get("duration") or 0,
        thumbnail=info.get("thumbnail"),
        stream_url=stream,
    )


def _usable_entries(info):
    out = []
    for e in (info or {}).get("entries") or []:
        if isinstance(e, dict) and (e.get("url") or e.get("webpage_url") or e.get("id")):
            out.append(e)
    return out


class TrackSelect(discord.ui.Select):
    def __init__(self, entries):
        self.entries = entries
        options = []
        for i, e in enumerate(entries[:25]):
            title = (e.get("title") or "Bilinmiyor")[:90]
            author = (e.get("channel") or e.get("uploader") or "Bilinmiyor")[:30]
            options.append(discord.SelectOption(label=f"{i+1}. {title}", description=author, value=str(i)))
        super().__init__(placeholder="Çalmak istediğin şarkıyı seç", options=options)

    async def callback(self, interaction: discord.Interaction):
        entry = self.entries[int(self.values[0])]
        view = self.view
        await interaction.response.defer(thinking=True)
        track = await view.cog._play_entry(interaction, entry)
        if track is None:
            await interaction.edit_original_response(content="❌ Bu şarkı çalınamadı.")
            return
        self.disabled = True
        await interaction.edit_original_response(view=view)


class TrackView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._states = {}
        self._always_cfg = None
        self._always_task = None
        self._always_fails = 0
        self._always_next_try = 0.0

    def _state(self, guild_id):
        return self._states.setdefault(
            guild_id,
            {
                "queue": [],
                "current": None,
                "volume": 100,
                "loop": "off",
                "started": None,
                "paused_at": None,
                "skipping": False,
                "stop_after": False,
                "restart_current": False,
                "seek_override": None,
                "resume_paused": False,
                "resume_pending": False,
                "idle_since": None,
            },
        )

    def _load_always_cfg(self):
        """7/24 hedefini config'ten çözer.

        Ayarlar sunucu bazlı tutulur (``guilds.<id>.voice_24_7``) ve
        ``voice_keep`` cogu da aynı yerden okur. Eski global ``voice_24_7``
        anahtarı geriye dönük uyumluluk için hâlâ kabul edilir."""
        cfg = database.load_config()
        for gid, override in cfg.get("guilds", {}).items():
            v = override.get("voice_24_7")
            if not v or not v.get("enabled"):
                continue
            try:
                return {
                    "guild_id": int(gid),
                    "channel_id": int(v["channel_id"]),
                    "enabled": True,
                }
            except (KeyError, TypeError, ValueError):
                continue
        v = cfg.get("voice_24_7")
        if v and v.get("enabled"):
            try:
                return {
                    "guild_id": int(v["guild_id"]),
                    "channel_id": int(v["channel_id"]),
                    "enabled": True,
                }
            except (KeyError, TypeError, ValueError):
                return None
        return None

    @commands.Cog.listener()
    async def on_ready(self):
        self._always_cfg = self._load_always_cfg()
        self._clean_stale_files()
        logger.info(
            "[Music] cookies.txt %s",
            "kullanilacak (YouTube linkleri acik)"
            if os.path.exists("cookies.txt")
            else "YOK - YouTube linkleri icin cookies.txt gerekli",
        )
        if self._always_cfg:
            self._start_always_voice()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            st = self._state(member.guild.id)
            if st["current"] is not None or st["queue"]:
                st["resume_pending"] = True
                asyncio.create_task(self._resume_after_drop(member.guild))

    async def _resume_after_drop(self, guild):
        st = self._state(guild.id)
        for _ in range(8):
            await asyncio.sleep(4)
            if not st.get("resume_pending"):
                return
            vc = guild.voice_client
            if vc is not None and vc.is_connected():
                break
            ch = None
            cfg = self._always_cfg
            if cfg and cfg.get("guild_id") == guild.id:
                g = self.bot.get_guild(cfg["guild_id"])
                if g:
                    ch = g.get_channel(cfg["channel_id"])
            if ch is None:
                continue
            try:
                vc = await ch.connect(reconnect=False)
                break
            except Exception:
                continue
        if vc is None or not vc.is_connected():
            st["resume_pending"] = False
            return
        st["resume_pending"] = False
        current = st["current"]
        if current is not None:
            await self._play_track(guild.id, vc, current)
        elif st["queue"]:
            await self._play_track(guild.id, vc, st["queue"].pop(0))

    def _start_always_voice(self):
        if self._always_task and not self._always_task.done():
            self._always_task.cancel()
        self._always_fails = 0
        self._always_next_try = 0.0
        self._always_task = asyncio.create_task(self._always_voice_loop())

    async def _always_voice_loop(self):
        while True:
            cfg = self._always_cfg
            if not cfg:
                return
            if time.monotonic() < self._always_next_try:
                await asyncio.sleep(5)
                continue
            guild = self.bot.get_guild(cfg["guild_id"])
            channel = guild.get_channel(cfg["channel_id"]) if guild else None
            vc = guild.voice_client if guild else None

            if vc is not None and vc.is_connected():
                st = self._state(cfg["guild_id"])
                busy = (
                    st["current"] is not None
                    or bool(st["queue"])
                    or vc.is_playing()
                    or vc.is_paused()
                )
                if busy:
                    st["idle_since"] = None
                else:
                    if st["idle_since"] is None:
                        st["idle_since"] = time.monotonic()
                    if (
                        channel
                        and vc.channel.id != channel.id
                        and time.monotonic() - st["idle_since"] >= IDLE_RETURN_SECONDS
                    ):
                        try:
                            await vc.move_to(channel)
                        except Exception as e:
                            logger.warning("7/24 kanala donus hatasi: %s", e)
                        st["idle_since"] = None
                await asyncio.sleep(30)
                continue

            if channel is None:
                await asyncio.sleep(30)
                continue

            if vc is not None:
                try:
                    vc.cleanup()
                except Exception:
                    pass
                vc = None

            try:
                await channel.connect(reconnect=False)
                self._always_fails = 0
                self._always_next_try = 0.0
            except Exception as e:
                logger.warning("7/24 ses baglanti hatasi: %s", e)
                self._always_fails += 1
                idx = min(self._always_fails - 1, len(ALWAYS_RETRY_DELAYS) - 1)
                self._always_next_try = time.monotonic() + ALWAYS_RETRY_DELAYS[idx]
            await asyncio.sleep(15)

    async def _save_always_cfg(self):
        cfg = database.load_config()
        cfg.pop("voice_24_7", None)
        guilds = cfg.setdefault("guilds", {})
        section = guilds.setdefault(str(self._always_cfg["guild_id"]), {})
        section["voice_24_7"] = {
            "enabled": True,
            "channel_id": self._always_cfg["channel_id"],
        }
        database.save_config(cfg)

    async def _connect_for(self, guild, member):
        if not member.voice or not member.voice.channel:
            raise app_commands.AppCommandError("Önce bir ses kanalına katılmalısın.")
        self._state(guild.id)["idle_since"] = None
        vc = guild.voice_client
        if vc is None:
            vc = await member.voice.channel.connect()
        elif not vc.is_connected():
            try:
                vc.cleanup()
            except Exception:
                pass
            vc = await member.voice.channel.connect()
        elif vc.channel.id != member.voice.channel.id:
            await vc.move_to(member.voice.channel)
        return vc

    def _active(self, guild_id, vc):
        return isinstance(vc, discord.VoiceClient) and vc.is_connected() and self._state(guild_id)["current"] is not None

    def _search_prefixes(self):
        provider = (database.load_config().get("music") or {}).get("search") or "auto"
        provider = str(provider).lower()
        if provider == "youtube":
            return ("ytsearch",)
        if provider == "soundcloud":
            return ("scsearch",)
        return ("ytsearch", "scsearch")

    async def _search(self, query, count=10):
        for prefix in self._search_prefixes():
            opts = dict(YDL_BASE, extract_flat=True, noplaylist=True)
            try:
                info = await asyncio.to_thread(
                    lambda p=prefix: yt_dlp.YoutubeDL(opts).extract_info(f"{p}{count}:{query}", download=False)
                )
            except Exception:
                continue
            entries = _usable_entries(info)
            if entries:
                return entries
        return []

    async def _resolve(self, entry):
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            return None
        opts = dict(YDL_BASE, extract_flat=False, noplaylist=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
        return info

    def _is_youtube(self, url):
        return "youtube.com" in url or "youtu.be" in url

    async def _youtube_title_oembed(self, url):
        oembed = f"https://www.youtube.com/oembed?url={url}&format=json"
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(oembed) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = (data.get("title") or "").strip()
                        if title:
                            return title
        except Exception:
            pass
        return None

    async def _sc_by_title(self, title, count=5):
        opts = dict(YDL_BASE, extract_flat=False, noplaylist=True)
        try:
            info = await asyncio.to_thread(
                lambda: yt_dlp.YoutubeDL(opts).extract_info(f"scsearch{count}:{title}", download=False)
            )
        except Exception:
            return None
        for e in _usable_entries(info):
            t = _to_track(e)
            if t:
                return t
        return None

    async def _resolve_playable(self, query):
        if query.startswith("http://") or query.startswith("https://"):
            opts = dict(YDL_BASE, extract_flat=False, noplaylist=False)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, query, download=False)
            if not info:
                if self._is_youtube(query):
                    title = await self._youtube_title_oembed(query)
                    if title:
                        fallback = await self._sc_by_title(title)
                        if fallback:
                            return [fallback], None
                return [], None
            if info.get("entries"):
                tracks = []
                for e in info["entries"]:
                    t = _to_track(e)
                    if t:
                        tracks.append(t)
                return tracks, info.get("title") or info.get("playlist_title")
            t = _to_track(info)
            if t:
                return [t], None
            if self._is_youtube(query):
                title = await self._youtube_title_oembed(query)
                if title:
                    fallback = await self._sc_by_title(title)
                    if fallback:
                        return [fallback], None
            return [], None

        for prefix in self._search_prefixes():
            count = 5 if prefix == "scsearch" else 1
            opts = dict(YDL_BASE, extract_flat=False, noplaylist=True)
            try:
                info = await asyncio.to_thread(
                    lambda p=prefix, c=count: yt_dlp.YoutubeDL(opts).extract_info(f"{p}{c}:{query}", download=False)
                )
            except Exception:
                continue
            for e in _usable_entries(info):
                t = _to_track(e)
                if t:
                    return [t], None
        return [], None

    async def _play_entry(self, interaction, entry):
        info = await self._resolve(entry)
        track = _to_track(info) if info else None
        if track is None:
            return None
        vc = await self._connect_for(interaction.guild, interaction.user)
        st = self._state(interaction.guild_id)
        if st["current"] is None:
            await self._play_track(interaction.guild_id, vc, track)
        else:
            st["queue"].append(track)
        embed = self._track_embed(
            "🎶 Kuyruğa Eklendi",
            track,
            st,
            color=discord.Color.blurple(),
        ) if st["current"] is not track else self._track_embed(
            "▶️ Şimdi Çalıyor", track, st, color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=ui.apply_animated(embed, interaction.guild))
        return track

    def _track_embed(self, title, track, st, color):
        embed = discord.Embed(
            title=title,
            description=f"**[{track.title}]({track.url})**\n🎤 {track.author}\n⏱ {_fmt(track.length)}",
            color=color,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text=f"Kuyruktaki sıra: {len(st['queue'])}")
        return embed

    async def _download_audio(self, track):
        """Şarkıyı yerel dosyaya indirir; 403/IP sorununu tamamen atlar.

        YouTube akış URL'leri çıkarım anındaki IP'ye kilitli olur; makinede
        dönen IPv6 adresleri yüzünden FFmpeg 403 alıp müziği çalamıyordu."""
        os.makedirs(TRACK_TMP, exist_ok=True)
        opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noplaylist": True,
            "outtmpl": os.path.join(TRACK_TMP, f"{uuid.uuid4().hex[:8]}_%(id)s.%(ext)s"),
            "extractor_args": {
                "youtube": {"player_client": _player_clients()},
            },
        }
        if os.path.exists("cookies.txt"):
            opts["cookiefile"] = "cookies.txt"
        try:
            info = await asyncio.to_thread(
                lambda: yt_dlp.YoutubeDL(opts).extract_info(track.url, download=True)
            )
        except Exception as e:
            logger.warning("Ses indirilemedi (%s): %s", track.title, e)
            return None
        dl = (info or {}).get("requested_downloads") or []
        if not dl:
            return None
        path = dl[0].get("filepath")
        if not path or not os.path.exists(path):
            return None
        return path

    def _clean_stale_files(self):
        try:
            if not os.path.isdir(TRACK_TMP):
                return
            for f in os.listdir(TRACK_TMP):
                p = os.path.join(TRACK_TMP, f)
                try:
                    if time.time() - os.path.getmtime(p) > 3600:
                        os.remove(p)
                except OSError:
                    pass
        except OSError:
            pass

    async def _play_track(self, guild_id, vc, track, seek=None):
        st = self._state(guild_id)
        st["current"] = track
        st["idle_since"] = None
        if seek is None:
            seek = st.pop("seek_override", None)
        else:
            st.pop("seek_override", None)
        st["started"] = time.perf_counter() - (seek or 0)
        st["paused_at"] = None

        vol = st["volume"] / 100
        options = f"-vn -filter:a volume={vol:.4f}" if abs(vol - 1.0) > 0.001 else "-vn"
        file_before = f"-ss {seek:.1f} " if seek else ""
        before = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        if seek:
            before = f"-ss {seek:.1f} " + before

        path = None
        if track.local_path and os.path.exists(track.local_path):
            path = track.local_path
        elif track.length:
            path = await self._download_audio(track)
        if path:
            track.local_path = path
            source = discord.FFmpegOpusAudio(
                path,
                executable=FFMPEG,
                bitrate=128,
                options=options,
                before_options=file_before,
            )
        else:
            # Canlı yayın veya indirme hatası: doğrudan akış dene.
            source = discord.FFmpegOpusAudio(
                track.stream_url,
                executable=FFMPEG,
                bitrate=128,
                options=options,
                before_options=before,
            )

        def _after(err):
            try:
                self.bot.loop.call_soon_threadsafe(
                    asyncio.create_task, self._on_track_end(guild_id, err)
                )
            except RuntimeError:
                pass

        for _ in range(50):
            if not vc.is_playing():
                break
            await asyncio.sleep(0.05)

        vc.play(source, after=_after)

    async def _on_track_end(self, guild_id, error):
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None
        st = self._state(guild_id)

        if error:
            logger.warning("Çalma hatası: %s", error)

        if vc is None or not vc.is_connected():
            if st.pop("stop_after", False):
                return
            if st["current"] is not None or st["queue"]:
                st["resume_pending"] = True
                return

        if st.pop("restart_current", False):
            if st["current"] and vc:
                await self._play_track(guild_id, vc, st["current"])
                if st.pop("resume_paused", False):
                    vc.pause()
                    st["paused_at"] = time.perf_counter()
            else:
                st["current"] = None
                st["started"] = None
            return

        current = st["current"]
        st["current"] = None
        st["started"] = None

        if current and current.local_path:
            try:
                os.remove(current.local_path)
            except OSError:
                pass
            current.local_path = None

        if st.pop("stop_after", False):
            return

        if vc is None:
            return

        if not st.pop("skipping", False):
            if st["loop"] == "one" and current:
                await self._play_track(guild_id, vc, current)
                return
            if st["loop"] == "all" and current:
                st["queue"].append(current)

        if st["queue"]:
            await self._play_track(guild_id, vc, st["queue"].pop(0))

    # ---------- cevap yardımcıları ----------

    @staticmethod
    def _fake_interaction(ctx):
        class _Fake:
            pass
        fake = _Fake()
        fake.guild = ctx.guild
        fake.user = ctx.author
        fake.created_at = ctx.message.created_at
        return fake

    def _message_kwargs(self, interaction, content, embed):
        if embed is not None:
            return {"embed": ui.apply_animated(embed, getattr(interaction, "guild", None))}
        if not content:
            return {}
        kind = "error" if content.startswith("❌") else ("warn" if content.startswith("⚠️") else "info")
        text = content
        for prefix in ("❌ ", "⚠️ ", "✅ ", "⏭️ ", "⏹️ ", "⏸️ ", "▶️ ", "🔀 ", "🔁 ", "🔊 ", "🎙️ ", "👋 ", "🗑️ ", "🧹 ", "🎶 ", "🎵 "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        return {"embed": ui.alert(kind, text, interaction=interaction)}

    async def _respond(self, interaction, content, embed=None):
        await interaction.response.send_message(**self._message_kwargs(interaction, content, embed))

    async def _ctx_respond(self, ctx, content, embed=None):
        fake = self._fake_interaction(ctx) if embed is None else None
        await ctx.send(**self._message_kwargs(fake, content, embed))

    # ---------- paylaşılan komut mantığı ----------

    async def _cmd_play(self, guild_id, vc, sorgu, added_only=False):
        try:
            tracks, name = await self._resolve_playable(sorgu)
        except Exception as e:
            return f"❌ Şarkı bulunamadı: {e}", None
        if not tracks:
            return "❌ Sonuç bulunamadı.", None
        st = self._state(guild_id)
        was_playing = st["current"] is not None
        if was_playing:
            st["queue"].extend(tracks)
        else:
            await self._play_track(guild_id, vc, tracks[0])
            st["queue"].extend(tracks[1:])
        if name:
            embed = discord.Embed(
                title="🎶 Çalma Listesi Eklendi",
                description=f"**{name}**\n🎵 {len(tracks)} şarkı kuyruğa eklendi.",
                color=discord.Color.blurple(),
            )
            return None, embed
        if was_playing or added_only:
            embed = self._track_embed(
                "🎶 Kuyruğa Eklendi", tracks[0], st, discord.Color.blurple()
            )
        else:
            embed = self._track_embed(
                "▶️ Şimdi Çalıyor", tracks[0], st, discord.Color.green()
            )
        return None, embed

    async def _cmd_ara_entries(self, sorgu):
        try:
            return await self._search(sorgu, 10)
        except Exception:
            return []

    def _cmd_ara_embed(self, entries):
        embed = discord.Embed(title="🔎 Arama Sonuçları", color=discord.Color.blurple())
        for i, e in enumerate(entries[:10]):
            embed.add_field(
                name=f"{i+1}. {e.get('title') or 'Bilinmiyor'}",
                value=(
                    f"🎤 {e.get('channel') or e.get('uploader') or 'Bilinmiyor'} • "
                    f"⏱ {_fmt(e.get('duration') or 0)}"
                ),
                inline=False,
            )
        return embed

    async def _cmd_kuyruk(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        embed = discord.Embed(
            title=f"📃 Kuyruk ({len(st['queue'])} şarkı)",
            description=f"**▶️ Şimdi:** {st['current'].title}",
            color=discord.Color.blurple(),
        )
        lines = []
        for i, t in enumerate(st["queue"], start=1):
            lines.append(f"`{i}.` {t.title} — {_fmt(t.length)}")
            if i >= 15:
                lines.append(f"*ve {len(st['queue']) - 15} daha...*")
                break
        embed.add_field(name="Sıradaki", value="\n".join(lines) or "Boş", inline=False)
        return None, embed

    async def _cmd_skip(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        st["skipping"] = True
        vc.stop()
        return "⏭️ Şarkı atlandı.", None

    async def _cmd_stop(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        st["queue"].clear()
        st["loop"] = "off"
        st["stop_after"] = True
        vc.stop()
        return "⏹️ Müzik durduruldu, kuyruk temizlendi.", None

    async def _cmd_pause(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        vc.pause()
        st["paused_at"] = time.perf_counter()
        return "⏸️ Duraklatıldı.", None

    async def _cmd_devam(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        vc.resume()
        if st["paused_at"]:
            st["started"] += time.perf_counter() - st["paused_at"]
            st["paused_at"] = None
        return "▶️ Devam ediyor.", None

    async def _cmd_karistir(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        if not st["queue"]:
            return "❌ Kuyruk boş.", None
        random.shuffle(st["queue"])
        return "🔀 Kuyruk karıştırıldı.", None

    async def _cmd_dongu(self, guild_id, vc, mod):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        st["loop"] = mod
        msg = {
            "off": "Döngü kapalı.",
            "one": "Tek şarkı döngüsü açık.",
            "all": "Tüm liste döngüsü açık.",
        }[mod]
        return f"🔁 {msg}", None

    async def _cmd_ses(self, guild_id, vc, seviye):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        seviye = max(0, min(200, seviye))
        st = self._state(guild_id)
        st["volume"] = seviye
        if vc.is_playing() or vc.is_paused():
            pos = 0
            if st["started"]:
                pos = (st["paused_at"] or time.perf_counter()) - st["started"]
            st["seek_override"] = pos
            st["resume_paused"] = st["paused_at"] is not None
            st["restart_current"] = True
            vc.stop()
        return f"🔊 Ses seviyesi: %{seviye}", None

    async def _cmd_sohbet(self, guild, kanal):
        matches = [c for c in guild.voice_channels if kanal.lower() in c.name.lower()]
        if not matches:
            names = ", ".join(c.name for c in guild.voice_channels) or "yok"
            return f"❌ '{kanal}' adında ses kanalı bulunamadı. Mevcut ses kanalları: {names}", None
        channel = matches[0]
        self._always_cfg = {"guild_id": guild.id, "channel_id": channel.id, "enabled": True}
        await self._save_always_cfg()
        self._start_always_voice()
        vc = guild.voice_client
        try:
            if vc is not None and vc.is_connected():
                await vc.move_to(channel)
            else:
                await channel.connect()
        except Exception as e:
            logger.warning("7/24 ilk baglanti hatasi: %s", e)
        return f"🎙️ **{channel.name}** kanalına 7/24 bağlı kalacağım.", None

    async def _cmd_leave(self, guild):
        vc = guild.voice_client
        if not isinstance(vc, discord.VoiceClient):
            return "❌ Ses kanalında değilim.", None
        st = self._state(guild.id)
        st["queue"].clear()
        st["current"] = None
        st["loop"] = "off"
        st["stop_after"] = True
        vc.stop()
        await vc.disconnect()
        self._always_cfg = None
        if self._always_task and not self._always_task.done():
            self._always_task.cancel()
        self._always_task = None
        cfg = database.load_config()
        cfg.pop("voice_24_7", None)
        section = cfg.get("guilds", {}).get(str(guild.id))
        if section is not None:
            section.pop("voice_24_7", None)
        database.save_config(cfg)
        return "👋 Ses kanalından çıktım, 7/24 modu kapatıldı.", None

    async def _cmd_nowplaying(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        t = st["current"]
        pos = 0
        if st["started"]:
            pos = (st["paused_at"] or time.perf_counter()) - st["started"]
        embed = discord.Embed(
            title="🎵 Şimdi Çalıyor",
            description=f"**[{t.title}]({t.url})**\n🎤 {t.author}",
            color=discord.Color.green(),
        )
        embed.add_field(name="Süre", value=f"`{_fmt(pos)} / {_fmt(t.length)}`\n{ui.bar(pos, t.length)}", inline=False)
        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)
        return None, embed

    async def _cmd_lyrics(self, guild_id, vc, sorgu):
        import aiohttp

        st = self._state(guild_id)
        if sorgu:
            query = sorgu
        elif isinstance(vc, discord.VoiceClient) and st["current"]:
            query = f"{st['current'].title} {st['current'].author}"
        else:
            query = None
        if not query:
            return "❌ Şarkı adı ver veya müzik çalıyor olsun.", None
        artist, _, title = query.partition(" ")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.lyrics.ovh/v1/{artist}/{title}") as resp:
                if resp.status != 200:
                    return "❌ Söz bulunamadı.", None
                data = await resp.json()
        text = data.get("lyrics", "Söz bulunamadı.")
        if len(text) > 4000:
            text = text[:4000] + "..."
        embed = discord.Embed(title=f"📝 {query}", description=text, color=discord.Color.blurple())
        return None, embed

    async def _cmd_kaldir(self, guild_id, vc, sira):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        if not 1 <= sira <= len(st["queue"]):
            return f"❌ Geçersiz sıra (kuyrukta {len(st['queue'])} şarkı var).", None
        t = st["queue"].pop(sira - 1)
        return f"🗑️ **{t.title}** kuyruktan çıkarıldı. Kalan: {len(st['queue'])}", None

    async def _cmd_atla(self, guild_id, vc, sira=None):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        if sira is not None:
            if not 1 <= sira <= len(st["queue"]):
                return f"❌ Geçersiz sıra (kuyrukta {len(st['queue'])} şarkı var).", None
            st["queue"] = st["queue"][sira - 1:]
        st["skipping"] = True
        vc.stop()
        return "⏭️ Atlandı.", None

    async def _cmd_temizle(self, guild_id, vc):
        if not self._active(guild_id, vc):
            return "❌ Şu an müzik çalmıyor.", None
        st = self._state(guild_id)
        n = len(st["queue"])
        st["queue"].clear()
        return f"🧹 Kuyruk temizlendi ({n} şarkı silindi).", None

    # ---------- slash komutlar ----------

    async def _run_play(self, interaction, sorgu, added_only=False):
        try:
            vc = await self._connect_for(interaction.guild, interaction.user)
        except app_commands.AppCommandError as e:
            return None, None, str(e)
        content, embed = await self._cmd_play(interaction.guild_id, vc, sorgu, added_only=added_only)
        return content, embed, None

    async def _run_ara(self, interaction, sorgu):
        try:
            await self._connect_for(interaction.guild, interaction.user)
        except app_commands.AppCommandError:
            return []
        return await self._cmd_ara_entries(sorgu)

    async def _finish_play(self, interaction, task):
        content, embed, error = await task
        final = ui.alert("error", error, interaction=interaction) if error else (embed or ui.alert("info", content, interaction=interaction))
        final = ui.apply_animated(final, interaction.guild)
        try:
            await interaction.edit_original_response(embed=final)
        except discord.HTTPException:
            pass

    @app_commands.command(name="play", description="Müzik çalar (şarkı adı veya YouTube bağlantısı)")
    async def play(self, interaction: discord.Interaction, sorgu: str):
        task = asyncio.create_task(self._run_play(interaction, sorgu))
        await ui.animate(interaction, defer=True, text="Müzik hazırlanıyor", emoji_="🎵", color="music", steps=6, delay=0.2)
        await self._finish_play(interaction, task)

    @app_commands.command(name="çal", description="Müzik çalar (şarkı adı veya YouTube bağlantısı)")
    async def cal(self, interaction: discord.Interaction, sorgu: str):
        task = asyncio.create_task(self._run_play(interaction, sorgu))
        await ui.animate(interaction, defer=True, text="Müzik hazırlanıyor", emoji_="🎵", color="music", steps=6, delay=0.2)
        await self._finish_play(interaction, task)

    @app_commands.command(name="ekle", description="Kuyruğa şarkı ekler (şarkı adı veya YouTube bağlantısı)")
    async def ekle(self, interaction: discord.Interaction, sorgu: str):
        task = asyncio.create_task(self._run_play(interaction, sorgu, added_only=True))
        await ui.animate(interaction, defer=True, text="Kuyruğa ekleniyor", emoji_="🎵", color="music", steps=6, delay=0.2)
        await self._finish_play(interaction, task)

    @app_commands.command(name="ara", description="Şarkı ara ve listeden seçerek çal")
    async def ara(self, interaction: discord.Interaction, sorgu: str):
        task = asyncio.create_task(self._run_ara(interaction, sorgu))
        await ui.animate(interaction, defer=True, text="Aranıyor", emoji_="🔎", color="music", steps=6, delay=0.2)
        entries = await task
        if not entries:
            await interaction.edit_original_response(embed=ui.alert("error", "Sonuç bulunamadı.", interaction=interaction))
            return
        view = TrackView(self)
        view.add_item(TrackSelect(entries))
        await interaction.edit_original_response(embed=ui.apply_animated(self._cmd_ara_embed(entries), interaction.guild), view=view)

    @app_commands.command(name="kuyruk", description="Çalma kuyruğunu gösterir")
    async def kuyruk(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_kuyruk(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="skip", description="Sıradaki şarkıya geçer")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_skip(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="stop", description="Müziği durdurur ve kuyruğu temizler")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_stop(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="pause", description="Müziği duraklatır")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_pause(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="devam", description="Müziği devam ettirir")
    async def devam(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_devam(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="karistir", description="Kuyruğu karıştırır")
    async def karistir(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_karistir(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="dongu", description="Döngü modunu ayarlar")
    @app_commands.choices(mod=[
        app_commands.Choice(name="Kapalı", value="off"),
        app_commands.Choice(name="Tek şarkı", value="one"),
        app_commands.Choice(name="Tüm liste", value="all"),
    ])
    async def dongu(self, interaction: discord.Interaction, mod: app_commands.Choice[str]):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_dongu(interaction.guild_id, vc, mod.value)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="ses", description="Müzik ses seviyesini ayarlar (0-200)")
    async def ses(self, interaction: discord.Interaction, seviye: app_commands.Range[int, 0, 200]):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_ses(interaction.guild_id, vc, seviye)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="sohbet", description="Bir ses kanalının adını yaz, bot oraya 7/24 bağlı kalsın")
    async def sohbet(self, interaction: discord.Interaction, kanal: str):
        content, embed = await self._cmd_sohbet(interaction.guild, kanal)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="leave", description="Botu ses kanalından çıkarır (7/24 modunu da kapatır)")
    async def leave(self, interaction: discord.Interaction):
        content, embed = await self._cmd_leave(interaction.guild)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="nowplaying", description="Çalan şarkıyı gösterir")
    async def nowplaying(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_nowplaying(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="lyrics", description="Çalan şarkının sözlerini arar")
    async def lyrics(self, interaction: discord.Interaction, sarki: str | None = None):
        task = asyncio.create_task(
            self._cmd_lyrics(interaction.guild_id, interaction.guild.voice_client, sarki)
        )
        await ui.animate(interaction, defer=True, text="Sözler aranıyor", emoji_="📝", color="music", steps=6, delay=0.2)
        content, embed = await task
        final = embed or ui.alert("error", content, interaction=interaction)
        final = ui.apply_animated(final, interaction.guild)
        try:
            await interaction.edit_original_response(embed=final)
        except discord.HTTPException:
            pass

    @app_commands.command(name="kaldır", description="Kuyruktan sıra numarasıyla şarkı çıkarır")
    async def kaldir(self, interaction: discord.Interaction, sira: int):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_kaldir(interaction.guild_id, vc, sira)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="atla", description="Sıradaki şarkıya veya belirtilen sıraya atlar")
    async def atla(self, interaction: discord.Interaction, sira: int | None = None):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_atla(interaction.guild_id, vc, sira)
        await self._respond(interaction, content, embed)

    @app_commands.command(name="temizle", description="Kuyruğu temizler (çalan şarkıya dokunmaz)")
    async def temizle(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        content, embed = await self._cmd_temizle(interaction.guild_id, vc)
        await self._respond(interaction, content, embed)

    # ---------- prefix (!) komutlar ----------

    @commands.command(name="play", aliases=["çal"], description="Müzik çalar (şarkı adı veya YouTube bağlantısı)")
    async def p_play(self, ctx, *, sorgu: str):
        await ctx.defer()
        try:
            vc = await self._connect_for(ctx.guild, ctx.author)
        except app_commands.AppCommandError as e:
            await ctx.send(str(e))
            return
        content, embed = await self._cmd_play(ctx.guild.id, vc, sorgu)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="ekle", description="Kuyruğa şarkı ekler (şarkı adı veya YouTube bağlantısı)")
    async def p_ekle(self, ctx, *, sorgu: str):
        await ctx.defer()
        try:
            vc = await self._connect_for(ctx.guild, ctx.author)
        except app_commands.AppCommandError as e:
            await ctx.send(str(e))
            return
        content, embed = await self._cmd_play(ctx.guild.id, vc, sorgu, added_only=True)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="ara", description="Şarkı ara")
    async def p_ara(self, ctx, *, sorgu: str):
        await ctx.defer()
        entries = await self._cmd_ara_entries(sorgu)
        if not entries:
            await ctx.send("❌ Sonuç bulunamadı.")
            return
        embed = self._cmd_ara_embed(entries)
        embed.set_footer(text="Çalmak için: !play <başlık veya bağlantı>")
        await ctx.send(embed=ui.apply_animated(embed, ctx.guild))

    @commands.command(name="kuyruk", description="Çalma kuyruğunu gösterir")
    async def p_kuyruk(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_kuyruk(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="skip", description="Sıradaki şarkıya geçer")
    async def p_skip(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_skip(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="stop", description="Müziği durdurur ve kuyruğu temizler")
    async def p_stop(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_stop(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="pause", description="Müziği duraklatır")
    async def p_pause(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_pause(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="devam", description="Müziği devam ettirir")
    async def p_devam(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_devam(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="karistir", description="Kuyruğu karıştırır")
    async def p_karistir(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_karistir(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="dongu", description="Döngü modunu ayarlar (off/one/all)")
    async def p_dongu(self, ctx, mod: str = "off"):
        m = mod.lower()
        if m in ("off", "kapat", "kapali", "kapalı", "0"):
            val = "off"
        elif m in ("one", "tek", "tekil", "1"):
            val = "one"
        elif m in ("all", "tum", "tüm", "liste", "hepsi", "2"):
            val = "all"
        else:
            await ctx.send("❌ Geçersiz mod. Seçenekler: off, one, all.")
            return
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_dongu(ctx.guild.id, vc, val)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="ses", description="Müzik ses seviyesini ayarlar (0-200)")
    async def p_ses(self, ctx, seviye: int = 100):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_ses(ctx.guild.id, vc, seviye)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="sohbet", description="Bir ses kanalının adını yaz, bot oraya 7/24 bağlı kalsın")
    async def p_sohbet(self, ctx, *, kanal: str):
        content, embed = await self._cmd_sohbet(ctx.guild, kanal)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="leave", description="Botu ses kanalından çıkarır (7/24 modunu da kapatır)")
    async def p_leave(self, ctx):
        content, embed = await self._cmd_leave(ctx.guild)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="nowplaying", aliases=["np"], description="Çalan şarkıyı gösterir")
    async def p_nowplaying(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_nowplaying(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="lyrics", description="Çalan şarkının sözlerini arar")
    async def p_lyrics(self, ctx, *, sarki: str | None = None):
        await ctx.defer()
        content, embed = await self._cmd_lyrics(ctx.guild.id, ctx.guild.voice_client, sarki)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="kaldır", description="Kuyruktan sıra numarasıyla şarkı çıkarır")
    async def p_kaldir(self, ctx, sira: int):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_kaldir(ctx.guild.id, vc, sira)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="atla", description="Sıradaki şarkıya veya belirtilen sıraya atlar")
    async def p_atla(self, ctx, sira: int | None = None):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_atla(ctx.guild.id, vc, sira)
        await self._ctx_respond(ctx, content, embed)

    @commands.command(name="temizle", description="Kuyruğu temizler (çalan şarkıya dokunmaz)")
    async def p_temizle(self, ctx):
        vc = ctx.guild.voice_client
        content, embed = await self._cmd_temizle(ctx.guild.id, vc)
        await self._ctx_respond(ctx, content, embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
