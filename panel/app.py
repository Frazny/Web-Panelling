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
)
from flask_session import Session

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

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)
# SECRET_KEY env'den okunur; yoksa sabit bir fallback kullanılır (production'da env'den set et)
app.secret_key = os.environ.get("SECRET_KEY", "frazny-panel-secret-do-not-use-in-prod-32x")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # http üzerinde çalışmak için

# Filesystem session — cookie yerine sunucuda sakla
_SESSION_DIR = os.path.join(BOT_DIR, "data", "flask_sessions")
os.makedirs(_SESSION_DIR, exist_ok=True)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = _SESSION_DIR
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400 * 7  # 7 gün
Session(app)

BOT_DIR = os.path.dirname(_BASE_DIR)  # panel/ klasörünün üstü = bot kök dizini
CONFIG_PATH = os.path.join(BOT_DIR, "config.json")
DB_PATH = os.path.join(BOT_DIR, "data", "bot.db")

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
DISCORD_API = "https://discord.com/api/v10"
DISCORD_CDN = "https://cdn.discordapp.com"


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
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        cfg = load_config()
        allowed = [cfg.get("owner_id")] + cfg.get("kurucu_users", [])
        if session["user"]["id"] not in allowed:
            return render_template("error.html", message="Yetkiniz yok.")
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

    session["user"] = user
    session["token"] = token
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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

    return render_template("dashboard.html", user=session["user"], config=cfg, stats=stats)


@app.route("/settings")
@owner_required
def settings():
    cfg = load_config()
    section = request.args.get("section", "general")
    return render_template("settings.html", user=session["user"], config=cfg, section=section)


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

    return jsonify(stats)


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
            leaderboard.append({
                "user_id": r[0],
                "xp": r[1],
                "messages": r[2],
                "voice_seconds": r[3],
            })
        db.close()
    except Exception:
        pass
    return render_template("levels.html", user=session["user"], leaderboard=leaderboard, config=cfg)


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
            leaderboard.append({"user_id": r[0], "balance": r[1]})
        db.close()
    except Exception:
        pass
    return render_template("economy.html", user=session["user"], leaderboard=leaderboard, config=cfg)


@app.route("/logs")
@owner_required
def logs():
    return render_template("logs.html", user=session["user"], config=load_config())


@app.route("/moderation")
@owner_required
def moderation():
    return render_template("moderation.html", user=session["user"], config=load_config())


@app.route("/tickets")
@owner_required
def tickets_page():
    return render_template("tickets.html", user=session["user"], config=load_config())


@app.route("/members")
@owner_required
def members():
    return render_template("members.html", user=session["user"], config=load_config())


@app.route("/cogs")
@owner_required
def cogs_page():
    return render_template("cogs.html", user=session["user"], config=load_config())


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
    mod_id = session["user"]["id"]
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
