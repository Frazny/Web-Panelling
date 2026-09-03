import json
import os
import secrets
import sqlite3
import time
from functools import wraps

import requests
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
    make_response,
)
import json
import hmac
import hashlib
import base64

# Cog yönetimi için IPC flag dizini
COG_IPC_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cog_ipc")

# Panelin bildiği tüm cog isimleri (main.py ile senkron)
ALL_COGS = [
    "cogs.guard", "cogs.moderation", "cogs.registration", "cogs.welcome",
    "cogs.levels", "cogs.invites", "cogs.tickets", "cogs.interface",
    "cogs.music", "cogs.economy", "cogs.logging", "cogs.utility",
    "cogs.rolemenu", "cogs.social", "cogs.management", "cogs.voice_keep",
    "cogs.automod", "cogs.emoji", "cogs.ai_chat", "cogs.gender",
    "cogs.manifest", "cogs.taglog",
]

# __file__ her zaman panel/app.py'yi gösterir — template/static dizinlerini buna göre belirt
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(_BASE_DIR)  # panel/ klasörünün üstü = bot kök dizini
CONFIG_PATH = os.path.join(BOT_DIR, "config.json")
DB_PATH = os.path.join(BOT_DIR, "data", "bot.db")

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)
_SECRET = os.environ.get("SECRET_KEY", "frazny-panel-secret-key-2024").encode()
app.secret_key = _SECRET
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400 * 7

# ── Basit JSON+HMAC token yardımcıları (flask-session gerektirmez) ──
def _make_token(data: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"

def _verify_token(token: str):
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return None

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
DISCORD_API = "https://discord.com/api/v10"
DISCORD_CDN = "https://cdn.discordapp.com"

# Kullanıcı bilgisi cache — API'yi çok sık çağırmamak için
_user_cache = {}
_user_cache_ttl = {}
_USER_CACHE_SECONDS = 300  # 5 dakika

def get_bot_token():
    """config.json'dan bot token'ı okur."""
    try:
        return load_config().get("token", "")
    except Exception:
        return os.environ.get("BOT_TOKEN", "")

def fetch_discord_user(user_id: str) -> dict:
    """Discord API'den kullanıcı bilgisi çeker, cache'ler."""
    now = time.time()
    if user_id in _user_cache and now - _user_cache_ttl.get(user_id, 0) < _USER_CACHE_SECONDS:
        return _user_cache[user_id]

    token = get_bot_token()
    if not token:
        return {"id": user_id, "username": str(user_id), "avatar": None}

    try:
        r = requests.get(
            f"{DISCORD_API}/users/{user_id}",
            headers={"Authorization": f"Bot {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            _user_cache[user_id] = data
            _user_cache_ttl[user_id] = now
            return data
    except Exception:
        pass

    fallback = {"id": user_id, "username": str(user_id), "avatar": None}
    _user_cache[user_id] = fallback
    _user_cache_ttl[user_id] = now
    return fallback

def user_avatar_url(user: dict, size: int = 64) -> str:
    uid = str(user.get("id", ""))
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"{DISCORD_CDN}/avatars/{uid}/{avatar}.{ext}?size={size}"
    # Default avatar
    discriminator = int(user.get("discriminator") or 0)
    idx = (int(uid) >> 22) % 6 if discriminator == 0 else discriminator % 5
    return f"{DISCORD_CDN}/embed/avatars/{idx}.png"

def user_display_name(user: dict) -> str:
    return user.get("global_name") or user.get("display_name") or user.get("username") or str(user.get("id", "?"))


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("panel_token")
        if not token:
            return redirect(url_for("login"))
        data = _verify_token(token)
        if not data or "user" not in data:
            return redirect(url_for("login"))
        request.panel_user = data["user"]
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("panel_token")
        if not token:
            return redirect(url_for("login"))
        data = _verify_token(token)
        if not data or "user" not in data:
            return redirect(url_for("login"))
        user = data["user"]
        request.panel_user = user
        cfg = load_config()
        allowed = [str(cfg.get("owner_id"))] + [str(x) for x in cfg.get("kurucu_users", [])]
        if str(user.get("id")) not in allowed:
            return render_template("error.html", message="Yetkiniz yok.", user=user)
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login")
def login():
    state = secrets.token_urlsafe(16)
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify+guilds"
        f"&state={state}"
    )
    return render_template("login.html", discord_url=url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("login"))

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(
            f"{DISCORD_API}/oauth2/token",
            data=data,
            headers=headers,
            auth=(DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET),
            timeout=10,
        )
        token_data = r.json()
    except Exception as e:
        return f"Token isteği hatası: {e}", 500

    token = token_data.get("access_token")
    if not token:
        # Hatayı kullanıcıya göster (debug için)
        return f"<pre>Token alınamadı!\nHTTP {r.status_code}\n{token_data}</pre>", 400

    try:
        r2 = requests.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        user = r2.json()

        r3 = requests.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        user["guilds"] = r3.json()
    except Exception as e:
        return f"Kullanıcı bilgisi hatası: {e}", 500

    panel_token = _make_token({
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "avatar": user.get("avatar"),
            "global_name": user.get("global_name"),
        },
        "discord_token": token,
    })
    resp = make_response(redirect(url_for("dashboard")))
    resp.set_cookie("panel_token", panel_token, max_age=86400*7, httponly=True, samesite="Lax")
    return resp

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.delete_cookie("panel_token")
    return resp


@app.route("/dashboard")
@owner_required
def dashboard():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    stats = {}

    try:
        db = get_db()
        cur = db.execute("SELECT COUNT(*) FROM levels WHERE guild_id = ?", (guild_id,))
        stats["total_members"] = cur.fetchone()[0]

        cur = db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,))
        stats["open_tickets"] = cur.fetchone()[0]

        cur = db.execute("SELECT COUNT(*) FROM warns WHERE guild_id = ?", (guild_id,))
        stats["total_warns"] = cur.fetchone()[0]

        cur = db.execute("SELECT SUM(balance) FROM economy WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        stats["total_balance"] = row[0] if row[0] else 0

        cur = db.execute("SELECT COUNT(*) FROM tags WHERE guild_id = ?", (guild_id,))
        stats["total_tags"] = cur.fetchone()[0]

        db.close()
    except Exception:
        stats = {
            "total_members": 0,
            "open_tickets": 0,
            "total_warns": 0,
            "total_balance": 0,
            "total_tags": 0,
        }

    return render_template("dashboard.html", user=request.panel_user, config=cfg, stats=stats)


@app.route("/settings")
@owner_required
def settings():
    cfg = load_config()
    section = request.args.get("section", "general")
    return render_template("settings.html", user=request.panel_user, config=cfg, section=section)


@app.route("/api/config", methods=["GET"])
@owner_required
def api_get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
@owner_required
def api_save_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    save_config(data)
    return jsonify({"ok": True})


@app.route("/api/config/section", methods=["POST"])
@owner_required
def api_save_section():
    data = request.get_json()
    section = data.get("section")
    values = data.get("values", {})
    if not section:
        return jsonify({"error": "No section"}), 400

    cfg = load_config()
    if isinstance(cfg.get(section), dict):
        cfg[section] = {**cfg[section], **values}
    else:
        cfg[section] = values
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/stats")
@owner_required
def api_stats():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    stats = {}
    try:
        db = get_db()

        cur = db.execute("SELECT COUNT(*) FROM levels WHERE guild_id = ?", (guild_id,))
        stats["total_members"] = cur.fetchone()[0]

        cur = db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,))
        stats["open_tickets"] = cur.fetchone()[0]

        cur = db.execute("SELECT COUNT(*) FROM warns WHERE guild_id = ?", (guild_id,))
        stats["total_warns"] = cur.fetchone()[0]

        cur = db.execute("SELECT SUM(balance) FROM economy WHERE guild_id = ?", (guild_id,))
        row = cur.fetchone()
        stats["total_balance"] = row[0] if row[0] else 0

        cur = db.execute("SELECT COUNT(*) FROM tags WHERE guild_id = ?", (guild_id,))
        stats["total_tags"] = cur.fetchone()[0]

        cur = db.execute("SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10", (guild_id,))
        stats["level_leaderboard"] = [{"user_id": r[0], "xp": r[1]} for r in cur.fetchall()]

        cur = db.execute("SELECT user_id, balance FROM economy WHERE guild_id = ? ORDER BY balance DESC LIMIT 10", (guild_id,))
        stats["economy_leaderboard"] = [{"user_id": r[0], "balance": r[1]} for r in cur.fetchall()]

        cur = db.execute("SELECT inviter_id, uses FROM invite_uses WHERE guild_id = ? ORDER BY uses DESC LIMIT 10", (guild_id,))
        stats["invite_leaderboard"] = [{"inviter_id": r[0], "uses": r[1]} for r in cur.fetchall()]

        db.close()
    except Exception:
        pass

    # Bot uptime flag dosyasından hesapla
    uptime_path = os.path.join(BOT_DIR, "data", "bot_start.txt")
    if os.path.exists(uptime_path):
        try:
            with open(uptime_path) as f:
                start_ts = float(f.read().strip())
            elapsed = int(time.time() - start_ts)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            stats["uptime"] = f"{h}s {m}d {s}sn"
            stats["uptime_seconds"] = elapsed
        except Exception:
            stats["uptime"] = "Bilinmiyor"
    else:
        stats["uptime"] = "Bilinmiyor"

    # Panel ping
    stats["panel_ping"] = "OK"
    stats["bot_online"] = os.path.exists(uptime_path)

    return jsonify(stats)


@app.route("/api/bot/status")
@owner_required
def api_bot_status():
    """Bot online durumu ve uptime kontrolü."""
    uptime_path = os.path.join(BOT_DIR, "data", "bot_start.txt")
    online = os.path.exists(uptime_path)
    uptime = "Bilinmiyor"
    uptime_pct = 0
    if online:
        try:
            with open(uptime_path) as f:
                start_ts = float(f.read().strip())
            elapsed = int(time.time() - start_ts)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            uptime = f"{h}s {m}d {s}sn"
            uptime_pct = min(100, int(elapsed / 86400 * 100))
        except Exception:
            pass
    return jsonify({"online": online, "uptime": uptime, "uptime_pct": uptime_pct})


@app.route("/api/moderation/warns/with_users")
@owner_required
def api_warns_with_users():
    """Warnları kullanıcı bilgileriyle birlikte döndürür."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    offset = (page - 1) * per_page
    warns = []
    total = 0
    try:
        db = get_db()
        cur = db.execute("SELECT COUNT(*) FROM warns WHERE guild_id = ?", (guild_id,))
        total = cur.fetchone()[0]
        cur = db.execute(
            "SELECT id, user_id, mod_id, reason, created FROM warns WHERE guild_id = ? ORDER BY created DESC LIMIT ? OFFSET ?",
            (guild_id, per_page, offset),
        )
        for r in cur.fetchall():
            u = fetch_discord_user(str(r[1]))
            m = fetch_discord_user(str(r[2]))
            warns.append({
                "id": r[0],
                "user_id": r[1],
                "user_name": user_display_name(u),
                "user_avatar": user_avatar_url(u, 32),
                "mod_id": r[2],
                "mod_name": user_display_name(m),
                "mod_avatar": user_avatar_url(m, 32),
                "reason": r[3],
                "created": r[4],
            })
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"warns": warns, "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page)})


@app.route("/api/members/list")
@owner_required
def api_members_list():
    """Tüm kayıtlı üyeleri sayfalı döndürür."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    search = request.args.get("search", "").strip()
    offset = (page - 1) * per_page
    members = []
    total = 0
    try:
        db = get_db()
        cur = db.execute("SELECT COUNT(*) FROM levels WHERE guild_id = ?", (guild_id,))
        total = cur.fetchone()[0]
        cur = db.execute(
            "SELECT l.user_id, l.xp, l.messages, l.voice_seconds, COALESCE(e.balance, 0) "
            "FROM levels l LEFT JOIN economy e ON l.guild_id = e.guild_id AND l.user_id = e.user_id "
            "WHERE l.guild_id = ? ORDER BY l.xp DESC LIMIT ? OFFSET ?",
            (guild_id, per_page, offset),
        )
        for r in cur.fetchall():
            u = fetch_discord_user(str(r[0]))
            name = user_display_name(u)
            if search and search.lower() not in name.lower() and search not in str(r[0]):
                continue
            members.append({
                "user_id": r[0],
                "username": name,
                "avatar": user_avatar_url(u, 32),
                "xp": r[1],
                "messages": r[2] or 0,
                "voice_minutes": (r[3] or 0) // 60,
                "balance": r[4] or 0,
            })
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"members": members, "total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page)})


@app.route("/api/tickets/with_users")
@owner_required
def api_tickets_with_users():
    """Ticketları kullanıcı bilgileriyle döndürür."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    status = request.args.get("status", "open")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    offset = (page - 1) * per_page
    tickets = []
    total = 0
    try:
        db = get_db()
        if status == "all":
            cur = db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ?", (guild_id,))
            total = cur.fetchone()[0]
            cur = db.execute(
                "SELECT channel_id, user_id, status, created_at FROM tickets WHERE guild_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (guild_id, per_page, offset),
            )
        else:
            cur = db.execute("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = ?", (guild_id, status))
            total = cur.fetchone()[0]
            cur = db.execute(
                "SELECT channel_id, user_id, status, created_at FROM tickets WHERE guild_id = ? AND status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (guild_id, status, per_page, offset),
            )
        for r in cur.fetchall():
            u = fetch_discord_user(str(r[1]))
            tickets.append({
                "channel_id": r[0],
                "user_id": r[1],
                "username": user_display_name(u),
                "avatar": user_avatar_url(u, 32),
                "status": r[2],
                "created_at": r[3],
            })
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"tickets": tickets, "total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page)})


@app.route("/api/charts/joins")
@owner_required
def api_chart_joins():
    """Son 30 günlük üye katılım verisi."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    days = []
    try:
        db = get_db()
        now = int(time.time())
        for i in range(29, -1, -1):
            day_start = now - (i + 1) * 86400
            day_end = now - i * 86400
            cur = db.execute(
                "SELECT COUNT(*) FROM joins WHERE guild_id = ? AND joined_at >= ? AND joined_at < ?",
                (guild_id, day_start, day_end),
            )
            count = cur.fetchone()[0]
            import datetime
            label = datetime.datetime.fromtimestamp(day_end).strftime("%d.%m")
            days.append({"label": label, "count": count})
        db.close()
    except Exception:
        pass
    return jsonify({"data": days})


@app.route("/api/charts/xp")
@owner_required
def api_chart_xp():
    """Top 10 XP dağılımı."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    result = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10",
            (guild_id,),
        )
        for r in cur.fetchall():
            u = fetch_discord_user(str(r[0]))
            result.append({"name": user_display_name(u), "xp": r[1]})
        db.close()
    except Exception:
        pass
    return jsonify({"data": result})


@app.route("/api/charts/economy")
@owner_required
def api_chart_economy():
    """Top 10 ekonomi dağılımı."""
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    result = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT user_id, balance FROM economy WHERE guild_id = ? ORDER BY balance DESC LIMIT 10",
            (guild_id,),
        )
        for r in cur.fetchall():
            u = fetch_discord_user(str(r[0]))
            result.append({"name": user_display_name(u), "balance": r[1]})
        db.close()
    except Exception:
        pass
    return jsonify({"data": result})


@app.route("/charts")
@owner_required
def charts():
    return render_template("charts.html", user=request.panel_user, config=load_config())


@app.route("/statistics")
@owner_required
def statistics():
    return render_template("statistics.html", user=request.panel_user, config=load_config())


@app.route("/modlogs")
@owner_required
def modlogs():
    return render_template("modlogs.html", user=request.panel_user, config=load_config())


@app.route("/message-send")
@owner_required
def message_send():
    cfg = load_config()
    channels = _get_guild_channels(cfg)
    return render_template("message_send.html", user=request.panel_user, config=cfg, channels=channels)


@app.route("/protection")
@owner_required
def protection():
    return render_template("protection.html", user=request.panel_user, config=load_config())


@app.route("/server-protection")
@owner_required
def server_protection():
    return render_template("server_protection.html", user=request.panel_user, config=load_config())


@app.route("/ai-antiraid")
@owner_required
def ai_antiraid():
    return render_template("ai_antiraid.html", user=request.panel_user, config=load_config())


@app.route("/auto-reply")
@owner_required
def auto_reply():
    return render_template("auto_reply.html", user=request.panel_user, config=load_config())


@app.route("/embed-builder")
@owner_required
def embed_builder():
    cfg = load_config()
    channels = _get_guild_channels(cfg)
    return render_template("embed_builder.html", user=request.panel_user, config=cfg, channels=channels)


@app.route("/auto-role")
@owner_required
def auto_role():
    return render_template("auto_role.html", user=request.panel_user, config=load_config())


@app.route("/voice")
@owner_required
def voice():
    return render_template("voice.html", user=request.panel_user, config=load_config())


@app.route("/music")
@owner_required
def music():
    return render_template("music.html", user=request.panel_user, config=load_config())


@app.route("/giveaway")
@owner_required
def giveaway():
    cfg = load_config()
    channels = _get_guild_channels(cfg)
    return render_template("giveaway.html", user=request.panel_user, config=cfg, channels=channels)


@app.route("/bot-settings")
@owner_required
def bot_settings():
    return render_template("bot_settings.html", user=request.panel_user, config=load_config())


@app.route("/backup")
@owner_required
def backup():
    return render_template("backup.html", user=request.panel_user, config=load_config())


@app.route("/account")
@owner_required
def account():
    return render_template("account.html", user=request.panel_user, config=load_config())


# ─────────────────────────────────────────────
# Yardımcı: Discord kanallarını çek
# ─────────────────────────────────────────────
def _get_guild_channels(cfg):
    guild_id = cfg.get("guild_id")
    token = get_bot_token()
    if not token or not guild_id:
        return []
    try:
        r = requests.get(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            chs = [c for c in r.json() if c.get("type") in (0, 2)]  # text + voice
            return sorted(chs, key=lambda c: c.get("position", 0))
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────
# API: Mesaj Gönder
# ─────────────────────────────────────────────

@app.route("/api/message/send", methods=["POST"])
@owner_required
def api_message_send():
    data = request.get_json()
    channel_id = data.get("channel_id")
    content = data.get("content", "").strip()
    if not channel_id or not content:
        return jsonify({"error": "channel_id ve content zorunlu"}), 400
    token = get_bot_token()
    if not token:
        return jsonify({"error": "Bot token bulunamadı"}), 500
    try:
        r = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"content": content},
            timeout=8,
        )
        if r.status_code in (200, 201):
            return jsonify({"ok": True})
        return jsonify({"error": f"Discord API: {r.status_code} {r.text}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/message/webhook", methods=["POST"])
@owner_required
def api_message_webhook():
    data = request.get_json()
    channel_id = data.get("channel_id")
    content = data.get("content", "").strip()
    if not channel_id or not content:
        return jsonify({"error": "channel_id ve content zorunlu"}), 400
    # Bot mesajı olarak gönder (webhook yoksa normal mesaj)
    return api_message_send()


# ─────────────────────────────────────────────
# API: Embed Gönder
# ─────────────────────────────────────────────

@app.route("/api/embed/send", methods=["POST"])
@owner_required
def api_embed_send():
    data = request.get_json()
    channel_id = data.get("channel_id")
    embed = data.get("embed", {})
    if not channel_id:
        return jsonify({"error": "channel_id zorunlu"}), 400
    token = get_bot_token()
    if not token:
        return jsonify({"error": "Bot token bulunamadı"}), 500
    try:
        r = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"embeds": [embed]},
            timeout=8,
        )
        if r.status_code in (200, 201):
            return jsonify({"ok": True})
        return jsonify({"error": f"Discord API: {r.status_code}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# API: Oto-Cevap (Tags tablosunu kullan)
# ─────────────────────────────────────────────

@app.route("/api/auto-reply")
@owner_required
def api_auto_reply_list():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    replies = []
    try:
        db = get_db()
        cur = db.execute("SELECT name, content FROM tags WHERE guild_id = ? ORDER BY name", (guild_id,))
        for r in cur.fetchall():
            replies.append({"trigger": r[0], "reply": r[1]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"replies": replies})


@app.route("/api/auto-reply", methods=["POST"])
@owner_required
def api_auto_reply_add():
    data = request.get_json()
    trigger = data.get("trigger", "").strip()
    reply = data.get("reply", "").strip()
    if not trigger or not reply:
        return jsonify({"error": "trigger ve reply zorunlu"}), 400
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    mod_id = request.panel_user.get("id", 0)
    try:
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO tags (guild_id, name, content, user_id) VALUES (?,?,?,?)",
            (guild_id, trigger, reply, int(mod_id)),
        )
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/auto-reply/<trigger>", methods=["DELETE"])
@owner_required
def api_auto_reply_delete(trigger):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("DELETE FROM tags WHERE guild_id = ? AND name = ?", (guild_id, trigger))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API: Ses (Voice)
# ─────────────────────────────────────────────

@app.route("/api/voice/join", methods=["POST"])
@owner_required
def api_voice_join():
    data = request.get_json()
    channel_id = data.get("channel_id")
    if not channel_id:
        return jsonify({"error": "channel_id zorunlu"}), 400
    # IPC flag ile bota sinyal gönder
    try:
        ipc_path = os.path.join(BOT_DIR, "data", "voice_cmd.json")
        with open(ipc_path, "w") as f:
            json.dump({"action": "join", "channel_id": int(channel_id), "ts": int(time.time())}, f)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice/leave", methods=["POST"])
@owner_required
def api_voice_leave():
    try:
        ipc_path = os.path.join(BOT_DIR, "data", "voice_cmd.json")
        with open(ipc_path, "w") as f:
            json.dump({"action": "leave", "ts": int(time.time())}, f)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# API: Çekilişler (Giveaways)
# ─────────────────────────────────────────────

@app.route("/api/giveaway/list")
@owner_required
def api_giveaway_list():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    giveaways = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT id, channel_id, end_at, winners, prize, done FROM giveaways WHERE guild_id = ? ORDER BY id DESC LIMIT 50",
            (guild_id,),
        )
        for r in cur.fetchall():
            giveaways.append({"id": r[0], "channel_id": r[1], "end_at": r[2], "winners": r[3], "prize": r[4], "done": r[5]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"giveaways": giveaways})


@app.route("/api/giveaway/create", methods=["POST"])
@owner_required
def api_giveaway_create():
    data = request.get_json()
    channel_id = data.get("channel_id")
    prize = data.get("prize", "").strip()
    winners = int(data.get("winners", 1))
    duration_minutes = int(data.get("duration_minutes", 10))
    if not channel_id or not prize:
        return jsonify({"error": "channel_id ve prize zorunlu"}), 400
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    end_at = int(time.time()) + duration_minutes * 60
    try:
        db = get_db()
        db.execute(
            "INSERT INTO giveaways (guild_id, message_id, channel_id, end_at, winners, prize) VALUES (?,?,?,?,?,?)",
            (guild_id, 0, int(channel_id), end_at, winners, prize),
        )
        db.commit()
        db.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/giveaway/<int:gw_id>/end", methods=["POST"])
@owner_required
def api_giveaway_end(gw_id):
    try:
        db = get_db()
        db.execute("UPDATE giveaways SET done = 1 WHERE id = ?", (gw_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/giveaway/<int:gw_id>", methods=["DELETE"])
@owner_required
def api_giveaway_delete(gw_id):
    try:
        db = get_db()
        db.execute("DELETE FROM giveaways WHERE id = ?", (gw_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# API: Yedekleme (Backup)
# ─────────────────────────────────────────────

@app.route("/api/backup/list")
@owner_required
def api_backup_list():
    backup_dir = os.path.join(BOT_DIR, "data", "backups")
    backups = []
    if os.path.exists(backup_dir):
        for fname in sorted(os.listdir(backup_dir), reverse=True):
            if fname.endswith(".json"):
                fpath = os.path.join(backup_dir, fname)
                try:
                    with open(fpath) as f:
                        b = json.load(f)
                    backups.append({
                        "id": fname.replace(".json", ""),
                        "code": b.get("code", fname[:12].upper()),
                        "created_at": int(os.path.getmtime(fpath)),
                        "roles": len(b.get("roles", [])),
                        "categories": len([c for c in b.get("channels", []) if c.get("type") == 4]),
                        "channels": len([c for c in b.get("channels", []) if c.get("type") != 4]),
                    })
                except Exception:
                    pass
    return jsonify({"backups": backups})


@app.route("/api/backup/create", methods=["POST"])
@owner_required
def api_backup_create():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    token = get_bot_token()
    if not token:
        return jsonify({"error": "Bot token bulunamadı"}), 500
    try:
        # Snapshot'tan al
        db = get_db()
        cur = db.execute("SELECT channel_id, data FROM channel_snapshot WHERE guild_id = ?", (guild_id,))
        channels = [json.loads(r[1]) for r in cur.fetchall()]
        cur = db.execute("SELECT role_id, data FROM role_snapshot WHERE guild_id = ?", (guild_id,))
        roles = [json.loads(r[1]) for r in cur.fetchall()]
        db.close()

        import datetime, random, string
        code = "KYZ-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        backup_data = {
            "code": code,
            "guild_id": guild_id,
            "created_at": int(time.time()),
            "channels": channels,
            "roles": roles,
        }
        backup_dir = os.path.join(BOT_DIR, "data", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        fpath = os.path.join(backup_dir, f"{code}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "code": code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backup/<backup_id>/restore", methods=["POST"])
@owner_required
def api_backup_restore(backup_id):
    # Restore işlemi bot tarafında yapılmalı, sadece flag bırak
    try:
        flag_path = os.path.join(BOT_DIR, "data", "restore_flag.json")
        with open(flag_path, "w") as f:
            json.dump({"backup_id": backup_id, "ts": int(time.time())}, f)
        return jsonify({"ok": True, "message": "Geri yükleme isteği gönderildi."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backup/<backup_id>", methods=["DELETE"])
@owner_required
def api_backup_delete(backup_id):
    backup_dir = os.path.join(BOT_DIR, "data", "backups")
    fpath = os.path.join(backup_dir, f"{backup_id}.json")
    try:
        if os.path.exists(fpath):
            os.remove(fpath)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/restart", methods=["POST"])
@owner_required
def api_restart():
    flag_path = os.path.join(BOT_DIR, "restart.flag")
    try:
        with open(flag_path, "w") as f:
            f.write(str(int(time.time())))
        return jsonify({"ok": True, "message": "Yeniden başlatma isteği gönderildi."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/levels")
@owner_required
def levels():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    leaderboard = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT user_id, xp, messages, voice_seconds FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 50",
            (guild_id,),
        )
        for r in cur.fetchall():
            user_info = fetch_discord_user(str(r[0]))
            leaderboard.append({
                "user_id": r[0],
                "xp": r[1],
                "messages": r[2],
                "voice_seconds": r[3],
                "username": user_display_name(user_info),
                "avatar": user_avatar_url(user_info, 64),
            })
        db.close()
    except Exception:
        pass
    return render_template("levels.html", user=request.panel_user, leaderboard=leaderboard, config=cfg)


@app.route("/economy")
@owner_required
def economy():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    leaderboard = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT user_id, balance FROM economy WHERE guild_id = ? ORDER BY balance DESC LIMIT 50",
            (guild_id,),
        )
        for r in cur.fetchall():
            user_info = fetch_discord_user(str(r[0]))
            leaderboard.append({
                "user_id": r[0],
                "balance": r[1],
                "username": user_display_name(user_info),
                "avatar": user_avatar_url(user_info, 64),
            })
        db.close()
    except Exception:
        pass
    return render_template("economy.html", user=request.panel_user, leaderboard=leaderboard, config=cfg)


@app.route("/logs")
@owner_required
def logs():
    return render_template("logs.html", user=request.panel_user, config=load_config())


@app.route("/moderation")
@owner_required
def moderation():
    return render_template("moderation.html", user=request.panel_user, config=load_config())


@app.route("/tickets")
@owner_required
def tickets_page():
    return render_template("tickets.html", user=request.panel_user, config=load_config())


@app.route("/members")
@owner_required
def members():
    return render_template("members.html", user=request.panel_user, config=load_config())


@app.route("/cogs")
@owner_required
def cogs_page():
    return render_template("cogs.html", user=request.panel_user, config=load_config())


# ─────────────────────────────────────────────
# API: Moderasyon — Warnlar
# ─────────────────────────────────────────────

@app.route("/api/moderation/warns")
@owner_required
def api_warns_all():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    warns = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT id, user_id, mod_id, reason, created FROM warns WHERE guild_id = ? ORDER BY created DESC LIMIT 50",
            (guild_id,),
        )
        for r in cur.fetchall():
            warns.append({"id": r[0], "user_id": r[1], "mod_id": r[2], "reason": r[3], "created": r[4]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"warns": warns})


@app.route("/api/moderation/warns/<int:user_id>")
@owner_required
def api_warns_user(user_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    warns = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT id, mod_id, reason, created FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY created DESC",
            (guild_id, user_id),
        )
        for r in cur.fetchall():
            warns.append({"id": r[0], "mod_id": r[1], "reason": r[2], "created": r[3]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"warns": warns})


@app.route("/api/moderation/warns", methods=["POST"])
@owner_required
def api_warn_add():
    data = request.get_json()
    user_id = data.get("user_id")
    reason = data.get("reason", "Panel üzerinden warn")
    if not user_id:
        return jsonify({"error": "user_id gerekli"}), 400
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    mod_id = request.panel_user["id"]
    try:
        db = get_db()
        db.execute(
            "INSERT INTO warns (guild_id, user_id, mod_id, reason, created) VALUES (?, ?, ?, ?, ?)",
            (guild_id, int(user_id), int(mod_id), reason, int(time.time())),
        )
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/moderation/warns/<int:warn_id>", methods=["DELETE"])
@owner_required
def api_warn_delete(warn_id):
    try:
        db = get_db()
        db.execute("DELETE FROM warns WHERE id = ?", (warn_id,))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/moderation/warns/clear/<int:user_id>", methods=["DELETE"])
@owner_required
def api_warns_clear(user_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("DELETE FROM warns WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API: Moderasyon — Punishments
# ─────────────────────────────────────────────

@app.route("/api/moderation/punishments")
@owner_required
def api_punishments():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    punishments = []
    try:
        db = get_db()
        cur = db.execute(
            "SELECT id, user_id, kind, until, reason FROM punishments WHERE guild_id = ? ORDER BY id DESC LIMIT 50",
            (guild_id,),
        )
        for r in cur.fetchall():
            punishments.append({"id": r[0], "user_id": r[1], "kind": r[2], "until": r[3], "reason": r[4]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"punishments": punishments})


@app.route("/api/moderation/punishments/<int:punishment_id>", methods=["DELETE"])
@owner_required
def api_punishment_delete(punishment_id):
    try:
        db = get_db()
        db.execute("DELETE FROM punishments WHERE id = ?", (punishment_id,))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API: Ticketlar
# ─────────────────────────────────────────────

@app.route("/api/tickets")
@owner_required
def api_tickets():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    status = request.args.get("status", "open")
    tickets = []
    try:
        db = get_db()
        if status == "all":
            cur = db.execute(
                "SELECT channel_id, user_id, status, created_at FROM tickets WHERE guild_id = ? ORDER BY created_at DESC LIMIT 100",
                (guild_id,),
            )
        else:
            cur = db.execute(
                "SELECT channel_id, user_id, status, created_at FROM tickets WHERE guild_id = ? AND status = ? ORDER BY created_at DESC LIMIT 100",
                (guild_id, status),
            )
        for r in cur.fetchall():
            tickets.append({"channel_id": r[0], "user_id": r[1], "status": r[2], "created_at": r[3]})
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"tickets": tickets})


@app.route("/api/tickets/<int:channel_id>/close", methods=["POST"])
@owner_required
def api_ticket_close(channel_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute(
            "UPDATE tickets SET status = 'closed' WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API: Üye Yönetimi
# ─────────────────────────────────────────────

@app.route("/api/members/<int:user_id>")
@owner_required
def api_member_get(user_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    result = {}
    try:
        db = get_db()

        cur = db.execute(
            "SELECT xp, messages, voice_seconds FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        if row:
            result["xp"] = row[0]
            result["messages"] = row[1] or 0
            result["voice_seconds"] = row[2] or 0
        else:
            result["xp"] = 0
            result["messages"] = 0
            result["voice_seconds"] = 0

        cur = db.execute(
            "SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cur.fetchone()
        result["balance"] = row[0] if row else 0

        cur = db.execute(
            "SELECT id, mod_id, reason, created FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY created DESC",
            (guild_id, user_id),
        )
        result["warns"] = [{"id": r[0], "mod_id": r[1], "reason": r[2], "created": r[3]} for r in cur.fetchall()]

        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(result)


@app.route("/api/members/<int:user_id>/edit", methods=["POST"])
@owner_required
def api_member_edit(user_id):
    data = request.get_json()
    edit_type = data.get("type")
    value = data.get("value")
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        if edit_type == "xp":
            db.execute(
                "INSERT OR REPLACE INTO levels (guild_id, user_id, xp) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?",
                (guild_id, user_id, value, value),
            )
        elif edit_type == "balance":
            db.execute(
                "INSERT OR REPLACE INTO economy (guild_id, user_id, balance) VALUES (?, ?, ?)",
                (guild_id, user_id, value),
            )
        else:
            return jsonify({"error": "Geçersiz tür"}), 400
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/members/whitelist")
@owner_required
def api_whitelist_get():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        cur = db.execute("SELECT user_id FROM whitelist WHERE guild_id = ?", (guild_id,))
        lst = [r[0] for r in cur.fetchall()]
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"list": lst})


@app.route("/api/members/whitelist", methods=["POST"])
@owner_required
def api_whitelist_add():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id gerekli"}), 400
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO whitelist (guild_id, user_id) VALUES (?, ?)", (guild_id, int(user_id)))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/members/whitelist/<int:user_id>", methods=["DELETE"])
@owner_required
def api_whitelist_remove(user_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("DELETE FROM whitelist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/members/blacklist")
@owner_required
def api_blacklist_get():
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        cur = db.execute("SELECT user_id FROM blacklist WHERE guild_id = ?", (guild_id,))
        lst = [r[0] for r in cur.fetchall()]
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"list": lst})


@app.route("/api/members/blacklist", methods=["POST"])
@owner_required
def api_blacklist_add():
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id gerekli"}), 400
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO blacklist (guild_id, user_id) VALUES (?, ?)", (guild_id, int(user_id)))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/members/blacklist/<int:user_id>", methods=["DELETE"])
@owner_required
def api_blacklist_remove(user_id):
    cfg = load_config()
    guild_id = cfg.get("guild_id")
    try:
        db = get_db()
        db.execute("DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        db.commit()
        db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API: Log Dosyası
# ─────────────────────────────────────────────

@app.route("/api/logs/file")
@owner_required
def api_log_file():
    allowed = {"bot_out": "bot_out.log", "bot_err": "bot_err.log"}
    file_key = request.args.get("file", "bot_out")
    lines_count = int(request.args.get("lines", 100))
    lines_count = min(lines_count, 500)

    filename = allowed.get(file_key)
    if not filename:
        return jsonify({"error": "Geçersiz dosya"}), 400

    log_path = os.path.join(BOT_DIR, filename)
    if not os.path.exists(log_path):
        return jsonify({"error": f"{filename} bulunamadı"})

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        content = "".join(all_lines[-lines_count:])
        return jsonify({"content": content, "total_lines": len(all_lines)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# API: Cog Yönetimi (flag tabanlı IPC)
# ─────────────────────────────────────────────

def _cog_state_path(cog_name):
    safe = cog_name.replace(".", "_")
    return os.path.join(COG_IPC_DIR, f"{safe}.state")


def _cog_cmd_path(cog_name):
    safe = cog_name.replace(".", "_")
    return os.path.join(COG_IPC_DIR, f"{safe}.cmd")


def _is_cog_loaded(cog_name):
    state_file = _cog_state_path(cog_name)
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                return f.read().strip() == "loaded"
        except Exception:
            return True
    # Durum dosyası yoksa varsayılan olarak yüklü kabul et
    return True


def _send_cog_cmd(cog_name, action):
    os.makedirs(COG_IPC_DIR, exist_ok=True)
    cmd_file = _cog_cmd_path(cog_name)
    with open(cmd_file, "w") as f:
        json.dump({"action": action, "ts": int(time.time())}, f)


@app.route("/api/cogs")
@owner_required
def api_cogs_list():
    cogs = []
    for cog in ALL_COGS:
        short = cog.split(".")[-1]
        cogs.append({"name": cog, "short": short, "loaded": _is_cog_loaded(cog)})
    return jsonify({"cogs": cogs})


@app.route("/api/cogs/reload", methods=["POST"])
@owner_required
def api_cog_reload():
    data = request.get_json()
    cog = data.get("cog")
    if not cog or cog not in ALL_COGS:
        return jsonify({"error": "Geçersiz cog"}), 400
    try:
        _send_cog_cmd(cog, "reload")
        return jsonify({"ok": True, "message": f"{cog} reload komutu gönderildi."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cogs/unload", methods=["POST"])
@owner_required
def api_cog_unload():
    data = request.get_json()
    cog = data.get("cog")
    if not cog or cog not in ALL_COGS:
        return jsonify({"error": "Geçersiz cog"}), 400
    try:
        _send_cog_cmd(cog, "unload")
        return jsonify({"ok": True, "message": f"{cog} unload komutu gönderildi."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cogs/load", methods=["POST"])
@owner_required
def api_cog_load():
    data = request.get_json()
    cog = data.get("cog")
    if not cog or cog not in ALL_COGS:
        return jsonify({"error": "Geçersiz cog"}), 400
    try:
        _send_cog_cmd(cog, "load")
        return jsonify({"ok": True, "message": f"{cog} load komutu gönderildi."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", os.environ.get("SERVER_PORT", os.environ.get("PORT", 5000))))
    app.run(host="0.0.0.0", port=port, debug=False)
