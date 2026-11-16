import json
import os
import sqlite3
from contextlib import contextmanager
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
IS_RENDER = bool(os.environ.get("RENDER"))

# Render: mount a persistent disk at /var/data and set
# FLUENTPATH_DB_PATH=/var/data/fluentpath.db.
# Local development: use fluentpath.db beside this file.
if os.environ.get("FLUENTPATH_DB_PATH"):
    DB_PATH = os.environ["FLUENTPATH_DB_PATH"]
elif os.environ.get("RENDER_DISK_PATH"):
    DB_PATH = os.path.join(os.environ["RENDER_DISK_PATH"], "fluentpath.db")
else:
    DB_PATH = os.path.join(BASE_DIR, "fluentpath.db")

DEFAULT_ADMIN_USER = os.environ.get("FLUENTPATH_ADMIN_USER", "admin").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.environ.get("FLUENTPATH_ADMIN_PASSWORD")

if not DEFAULT_ADMIN_PASSWORD:
    if IS_RENDER:
        raise RuntimeError(
            "Set FLUENTPATH_ADMIN_PASSWORD in Render Environment before starting."
        )
    DEFAULT_ADMIN_PASSWORD = "N4kul140"  # Local development only.

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
if not SECRET_KEY:
    if IS_RENDER:
        raise RuntimeError(
            "Set FLASK_SECRET_KEY in Render Environment before starting."
        )
    SECRET_KEY = "fluentpath-local-development-secret-change-before-hosting"

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_RENDER,
)


@contextmanager
def db():
    """Open a SQLite connection and always close it after use."""
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and seed the admin only when the account is absent."""
    with db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                state_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )

        existing = con.execute(
            "SELECT id FROM users WHERE username = ?",
            (DEFAULT_ADMIN_USER,),
        ).fetchone()

        if existing is None:
            con.execute(
                """
                INSERT INTO users
                    (username, display_name, password_hash, is_admin, state_json)
                VALUES (?, ?, ?, 1, '{}')
                """,
                (
                    DEFAULT_ADMIN_USER,
                    "FluentPath Admin",
                    generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                ),
            )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as con:
        return con.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
@login_required
def home():
    user = current_user()
    return render_template(
        "index.html",
        current_user=user["display_name"],
        is_admin=bool(user["is_admin"]),
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("display_name", "").strip() or username
        password = request.form.get("password", "")

        if len(username) < 3 or len(password) < 6:
            error = "Username must have at least 3 characters and password at least 6."
        else:
            try:
                with db() as con:
                    cur = con.execute(
                        """
                        INSERT INTO users
                            (username, display_name, password_hash, state_json)
                        VALUES (?, ?, ?, '{}')
                        """,
                        (username, name, generate_password_hash(password)),
                    )
                    new_user_id = cur.lastrowid
                session.clear()
                session["user_id"] = new_user_id
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                error = "That username is already taken."

    return render_template("auth.html", mode="signup", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        with db() as con:
            user = con.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("admin" if user["is_admin"] else "home"))

        error = "Incorrect username or password."

    return render_template("auth.html", mode="login", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/state", methods=["GET", "POST"])
@login_required
def api_state():
    user = current_user()

    if request.method == "GET":
        try:
            state = json.loads(user["state_json"] or "{}")
        except (TypeError, ValueError):
            state = {}
        return jsonify({"state": state})

    payload = request.get_json(silent=True) or {}
    state = payload.get("state", {})
    if not isinstance(state, dict):
        return jsonify({"error": "Invalid state"}), 400

    with db() as con:
        con.execute(
            "UPDATE users SET state_json = ? WHERE id = ?",
            (json.dumps(state, ensure_ascii=False), user["id"]),
        )
    return jsonify({"ok": True})


@app.route("/admin")
@admin_required
def admin():
    with db() as con:
        users = con.execute(
            """
            SELECT id, username, display_name, is_admin
            FROM users ORDER BY id
            """
        ).fetchall()
    return render_template(
        "admin.html", users=users, message=request.args.get("message")
    )


def update_state(con, user_id, fn):
    row = con.execute(
        "SELECT state_json FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return

    try:
        state = json.loads(row["state_json"] or "{}")
    except (TypeError, ValueError):
        state = {}

    fp = state.get("fluentpath-v2", {})
    if not isinstance(fp, dict):
        fp = {}

    fn(fp)
    state["fluentpath-v2"] = fp
    con.execute(
        "UPDATE users SET state_json = ? WHERE id = ?",
        (json.dumps(state, ensure_ascii=False), user_id),
    )


THEME_IDS = [
    "classic", "spider", "barbie", "bmw", "gold", "silver", "galaxy",
    "neon", "batman", "ironman", "lambo", "ferrari", "minecraft",
    "ocean", "forest", "sakura", "royal", "diamond", "midnight",
    "sunset", "glacier", "fire", "nature", "minimal", "rgb", "crystal",
    "rainbow", "bronze", "milestone-silver", "milestone-animated",
    "legendary", "cyberpunk", "aurora", "arctic-night",
    "barbie-motion", "bmw-night",
]


@app.route("/admin/action", methods=["POST"])
@admin_required
def admin_action():
    action = request.form.get("action")
    message = "No action was performed."

    with db() as con:
        if action == "unlock_all":
            ids = [
                row["id"]
                for row in con.execute(
                    "SELECT id FROM users WHERE is_admin = 0"
                )
            ]

            def unlock(fp):
                fp["developer"] = True
                fp["level"] = 100
                fp["xp"] = max(10000, int(fp.get("xp", 0)))
                fp["coins"] = max(999999, int(fp.get("coins", 0)))
                fp["unlockedThemes"] = THEME_IDS.copy()
                fp["unlockedFeatures"] = [
                    "all-lessons", "all-exams", "premium-writing", "all-animations"
                ]

            for user_id in ids:
                update_state(con, user_id, unlock)
            message = f"Unlocked all features for {len(ids)} learner account(s)."

        elif action in ("set_level", "add_coins", "unlock_themes"):
            try:
                user_id = int(request.form.get("user_id", 0))
            except (TypeError, ValueError):
                user_id = 0

            if action == "set_level":
                try:
                    level = max(1, min(100, int(request.form.get("level", 1))))
                    xp = max(0, int(request.form.get("xp", level * 100)))
                except (TypeError, ValueError):
                    level, xp = 1, 100

                def set_level(fp):
                    fp["level"] = level
                    fp["xp"] = max(xp, level * 100 - 100)
                    fp["developer"] = level >= 100

                update_state(con, user_id, set_level)
                message = "Learner level and XP updated."

            elif action == "add_coins":
                try:
                    amount = max(0, int(request.form.get("coins", 0)))
                except (TypeError, ValueError):
                    amount = 0

                update_state(
                    con,
                    user_id,
                    lambda fp: fp.update(
                        coins=int(fp.get("coins", 0)) + amount
                    ),
                )
                message = "Coins added."

            else:
                def unlock_themes(fp):
                    fp["developer"] = True
                    fp["unlockedThemes"] = THEME_IDS.copy()

                update_state(con, user_id, unlock_themes)
                message = "All themes unlocked for that learner."

    return redirect(url_for("admin", message=message))


@app.errorhandler(404)
def not_found(_error):
    return "Page not found. Return to FluentPath.", 404


# Gunicorn imports this module, so initialize the database at import time too.
# This is safe because init_db() only creates the table and seeds a missing admin.
init_db()


if __name__ == "__main__":
    app.run(debug=not IS_RENDER)
