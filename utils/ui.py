"""Komut çıktılarını zenginleştiren ortak arayüz yardımcıları.

- ``embed``      : temalı, yazarlı, ayaklı (footer) embed üretir
- ``bar``        : blok tabanlı ilerleme çubuğu
- ``countdown``  : saniyeyi insan diline çevirir
- ``animate``    : canlı "işleniyor" animasyonu gösterip sonuç embed'ine geçer
- ``alert``      : hızlı başarı/hata/uyarı embed'leri
"""

import asyncio

import discord

COLORS = {
    "success": 0x2ECC71,
    "error": 0xE74C3C,
    "warn": 0xE67E22,
    "info": 0x5865F2,
    "gold": 0xF1C40F,
    "music": 0x9B59B6,
    "money": 0xF1C40F,
    "level": 0xF39C12,
    "teal": 0x1ABC9C,
    "pink": 0xE91E63,
    "guard": 0xC0392B,
    "purple": 0x8E44AD,
}

_EMOJI_MAP = {
    "success": "✅",
    "error": "❌",
    "warn": "⚠️",
    "info": "ℹ️",
    "gold": "🏆",
    "music": "🎵",
    "money": "💰",
    "level": "⭐",
    "teal": "📨",
    "pink": "💖",
    "guard": "🛡️",
    "purple": "🟣",
}


def color(name="info"):
    return discord.Color(COLORS.get(name, COLORS["info"]))


def emoji(name):
    return _EMOJI_MAP.get(name, "✨")


# Sunucuya yüklenen animasyonlu emojilerin adları (cogs/emoji paketi).
# Statik emoji -> animasyonlu emoji adı eşleşmesi.
ANIM_EMOJI = {
    "✅": "anim_onay",
    "❌": "anim_red",
    "⚠️": "anim_uyari",
    "🛡️": "anim_kalkan",
    "💰": "anim_para",
    "💎": "anim_elmas",
    "🎵": "anim_muzik",
    "🏆": "anim_kupa",
    "🔒": "anim_kilit",
    "🔓": "anim_kilit_acik",
    "⭐": "anim_yildiz",
    "✨": "anim_isik",
    "❤️": "anim_kalp",
    "🗑️": "anim_cop",
    "🎉": "anim_parti",
    "📋": "anim_liste",
    "📥": "anim_indir",
    "📨": "anim_davet",
    "🔨": "anim_ban",
    "🚫": "anim_yasak",
    "🎁": "anim_hediye",
    "🎫": "anim_bilet",
    "👢": "anim_tekme",
    "🤐": "anim_sus",
    "📊": "anim_grafik",
    "🔊": "anim_ses",
    "🎶": "anim_melodi",
    "🥇": "anim_altin",
    "📝": "anim_kayit",
    "🎯": "anim_hedef",
    "🎤": "anim_mikrofon",
    "📢": "anim_duyuru",
    "🤖": "anim_robot",
    "🟢": "anim_yesil",
    "🔴": "anim_kirmizi",
    "💸": "anim_ucan",
    "🎰": "anim_kumar",
}


def _find_emoji(guild, name):
    if guild is None:
        return None
    for e in guild.emojis:
        if e.name == name:
            return e
    return None


def animated(text, guild):
    """Metindeki statik emojileri, sunucuda varsa animasyonlu karşılığıyla değiştirir."""
    if guild is None or not text:
        return text
    for base, name in ANIM_EMOJI.items():
        emo = _find_emoji(guild, name)
        if emo is None:
            continue
        rep = str(emo)
        variants = {base, base + "\uFE0F", base.replace("\uFE0F", "")}
        for v in sorted(variants, key=len, reverse=True):
            if v in text:
                text = text.replace(v, rep)
    return text


def apply_animated(embed, guild):
    """Embed içeriğindeki statik emojileri animasyonlu karşılıklarıyla değiştirir."""
    if embed is None or guild is None:
        return embed
    if embed.title:
        embed.title = animated(embed.title, guild)
    if embed.description:
        embed.description = animated(embed.description, guild)
    for field in getattr(embed, "_fields", []):
        if field.get("name"):
            field["name"] = animated(field["name"], guild)
        if field.get("value"):
            field["value"] = animated(field["value"], guild)
    footer = getattr(embed, "_footer", None)
    if footer and footer.get("text"):
        footer["text"] = animated(footer["text"], guild)
    author = getattr(embed, "_author", None)
    if author and author.get("name"):
        author["name"] = animated(author["name"], guild)
    return embed


def footer_text(interaction, extra=None):
    parts = []
    if interaction.guild:
        parts.append(interaction.guild.name)
    if extra:
        parts.append(extra)
    return " • ".join(parts) or None


def embed(title=None, description=None, color="info", interaction=None, footer=True, timestamp=False, emoji_="", author=True):
    """Temalı, yazarlı ve ayaklı (footer) bir embed döndürür."""
    if title and emoji_ and not str(title).startswith(emoji_):
        title = f"{emoji_} {title}"
    e = discord.Embed(title=title, description=description, color=discord.Color(COLORS.get(color, COLORS["info"])))
    if interaction is not None:
        if author:
            e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        if footer:
            e.set_footer(text=footer_text(interaction))
        if timestamp:
            e.timestamp = interaction.created_at
        guild = getattr(interaction, "guild", None)
        if guild is not None:
            e = apply_animated(e, guild)
    return e


def bar(value, total, width=14, fill="█", empty="░"):
    if total <= 0:
        return fill * width
    n = int(width * max(0.0, min(value / total, 1.0)))
    return fill * n + empty * (width - n)


def countdown(seconds):
    """Saniyeyi '1 saat 30 dakika' gibi okunaklı bir metne çevirir."""
    seconds = int(seconds)
    if seconds <= 0:
        return "0 saniye"
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
    if secs and not days:
        parts.append(f"{secs} saniye")
    return ", ".join(parts[:3]) if parts else "0 saniye"


def _processing_embed(text, step, total, emoji_, color, interaction, detail=None, guild=None):
    pct = int(100 * step / total)
    e = discord.Embed(
        title=f"{emoji_} {text}",
        description=(
            f"`{bar(step, total, width=16)}` `%{pct}`\n"
            f"*{step}/{total} adım*"
        ),
        color=discord.Color(COLORS.get(color, COLORS["info"])),
    )
    if detail:
        e.add_field(name="Detay", value=detail, inline=False)
    if interaction is not None:
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    e.set_footer(text="Lütfen bekleyin…")
    if guild is None and interaction is not None:
        guild = getattr(interaction, "guild", None)
    if guild is not None:
        e = apply_animated(e, guild)
    return e


async def animate(
    interaction,
    final=None,
    *,
    text="İşleniyor",
    emoji_="✨",
    color="info",
    detail=None,
    steps=6,
    delay=0.18,
    ephemeral=False,
    defer=False,
    view=None,
):
    """Canlı yükleme animasyonu gösterir, ardından ``final`` içeriğine geçer.

    ``final`` bir ``discord.Embed`` veya ``str`` olabilir. ``defer=True``
    verilirse önce ``defer(thinking=True)`` çağrılır (ağır işlemler için).
    Mesajı daha sonra düzenlemek için kullanılabilecek ``edit`` callback'ini
    döndürür.
    """
    if defer:
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        edit = interaction.edit_original_response
        start = 0
    else:
        await interaction.response.send_message(
            embed=_processing_embed(text, 0, steps, emoji_, color, interaction, detail),
            ephemeral=ephemeral,
        )
        edit = interaction.edit_original_response
        start = 1

    for i in range(start, steps + 1):
        await asyncio.sleep(delay)
        try:
            await edit(
                embed=_processing_embed(text, i, steps, emoji_, color, interaction, detail),
                content=None,
            )
        except discord.HTTPException:
            break

    if final is not None:
        guild = getattr(interaction, "guild", None)
        kw = {"view": view}
        if isinstance(final, discord.Embed):
            kw["embed"] = apply_animated(final, guild)
            kw["content"] = None
        elif isinstance(final, str):
            kw["content"] = final
            kw["embed"] = None
        try:
            await edit(**kw)
        except discord.HTTPException:
            pass
    return edit


def alert(kind, text, interaction=None, title=None, **kw):
    """Kısa başarı/hata/uyarı mesajı için hazır embed."""
    name = kind if kind in COLORS else "info"
    return embed(
        title=title or emoji(name),
        description=text,
        color=name,
        interaction=interaction,
        **kw,
    )


async def animate_message(
    channel,
    final=None,
    *,
    text="İşleniyor",
    emoji_="✨",
    color="info",
    detail=None,
    steps=5,
    delay=0.18,
    view=None,
):
    """Bir kanala canlı yükleme animasyonu atar (interaction gerektirmez).

    Listener içinden (ör. rol logları) mesaj tabanlı animasyon göstermek için
    kullanılır. ``final`` bir ``discord.Embed`` veya ``str`` olabilir.
    """
    message = await channel.send(embed=_processing_embed(text, 0, steps, emoji_, color, None, detail, channel.guild))
    for i in range(1, steps + 1):
        await asyncio.sleep(delay)
        try:
            await message.edit(embed=_processing_embed(text, i, steps, emoji_, color, None, detail, channel.guild))
        except discord.HTTPException:
            break
    if final is not None:
        if isinstance(final, discord.Embed):
            kw = {"embed": apply_animated(final, channel.guild)}
            if view is not None:
                kw["view"] = view
            await message.edit(**kw)
        elif isinstance(final, str):
            await message.edit(content=final, embed=None)
    return message
