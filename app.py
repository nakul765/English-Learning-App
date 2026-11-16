import os, json, sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fluentpath-local-development-secret-change-before-hosting")
DB_PATH = os.path.join(BASE_DIR, "fluentpath.db")
DEFAULT_ADMIN_USER = os.environ.get("FLUENTPATH_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("FLUENTPATH_ADMIN_PASSWORD", "N4kul140")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            state_json TEXT NOT NULL DEFAULT '{}'
        )""")
        existing = con.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USER,)).fetchone()
        if not existing:
            con.execute("INSERT INTO users(username,display_name,password_hash,is_admin,state_json) VALUES(?,?,?,?,?)",
                (DEFAULT_ADMIN_USER, "FluentPath Admin", generate_password_hash(DEFAULT_ADMIN_PASSWORD), 1, "{}"))
        else:
            # Keep the seeded admin login aligned with the configured default on existing local databases.
            con.execute("UPDATE users SET password_hash=?, is_admin=1 WHERE id=?",
                (generate_password_hash(DEFAULT_ADMIN_PASSWORD), existing["id"]))

def current_user():
    if not session.get("user_id"): return None
    with db() as con:
        return con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user(): return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u=current_user()
        if not u or not u["is_admin"]: return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
@login_required
def home():
    u=current_user()
    return render_template("index.html", current_user=u["display_name"], is_admin=bool(u["is_admin"]))

@app.route("/signup", methods=["GET","POST"])
def signup():
    error=None
    if request.method=="POST":
        username=request.form.get("username","").strip().lower()
        name=request.form.get("display_name","").strip() or username
        password=request.form.get("password","")
        if len(username)<3 or len(password)<6:
            error="Username must have at least 3 characters and password at least 6."
        else:
            try:
                with db() as con:
                    cur=con.execute("INSERT INTO users(username,display_name,password_hash,state_json) VALUES(?,?,?,?)",
                        (username,name,generate_password_hash(password),"{}"))
                    session.clear(); session["user_id"]=cur.lastrowid
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                error="That username is already taken."
    return render_template("auth.html", mode="signup", error=error)

@app.route("/login", methods=["GET","POST"])
def login():
    error=None
    if request.method=="POST":
        username=request.form.get("username","").strip().lower()
        password=request.form.get("password","")
        with db() as con: u=con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if u and check_password_hash(u["password_hash"],password):
            session.clear(); session["user_id"]=u["id"]
            return redirect(url_for("admin" if u["is_admin"] else "home"))
        error="Incorrect username or password."
    return render_template("auth.html", mode="login", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/api/state", methods=["GET","POST"])
@login_required
def api_state():
    u=current_user()
    if request.method=="GET":
        try: state=json.loads(u["state_json"] or "{}")
        except Exception: state={}
        return jsonify({"state":state})
    payload=request.get_json(silent=True) or {}
    state=payload.get("state",{})
    if not isinstance(state,dict): return jsonify({"error":"Invalid state"}),400
    # Store only the current learner's state in their own database row.
    with db() as con: con.execute("UPDATE users SET state_json=? WHERE id=?", (json.dumps(state,ensure_ascii=False),u["id"]))
    return jsonify({"ok":True})

@app.route("/admin")
@admin_required
def admin():
    with db() as con: users=con.execute("SELECT id,username,display_name,is_admin FROM users ORDER BY id").fetchall()
    return render_template("admin.html", users=users, message=request.args.get("message"))

def update_state(con, user_id, fn):
    row=con.execute("SELECT state_json FROM users WHERE id=?", (user_id,)).fetchone()
    try: state=json.loads(row["state_json"] or "{}")
    except Exception: state={}
    fp=state.get("fluentpath-v2", {})
    if not isinstance(fp,dict): fp={}
    fn(fp)
    state["fluentpath-v2"]=fp
    con.execute("UPDATE users SET state_json=? WHERE id=?", (json.dumps(state,ensure_ascii=False),user_id))

@app.route("/admin/action", methods=["POST"])
@admin_required
def admin_action():
    action=request.form.get("action")
    with db() as con:
        if action=="unlock_all":
            ids=[r["id"] for r in con.execute("SELECT id FROM users WHERE is_admin=0")]
            def unlock(fp):
                fp["developer"]=True; fp["level"]=100; fp["xp"]=max(10000,int(fp.get("xp",0)))
                fp["coins"]=max(999999,int(fp.get("coins",0)))
                fp["unlockedThemes"]=["classic","spider","barbie","bmw","gold","silver","galaxy","neon","batman","ironman","lambo","ferrari","minecraft","ocean","forest","sakura","royal","diamond","midnight","sunset","glacier","fire","nature","minimal","rgb","crystal","rainbow","bronze","milestone-silver","milestone-animated","legendary","cyberpunk","aurora","arctic-night","barbie-motion","bmw-night"]
                fp["unlockedFeatures"]=["all-lessons","all-exams","premium-writing","all-animations"]
            for uid in ids: update_state(con,uid,unlock)
            message=f"Unlocked all features for {len(ids)} learner account(s)."
        elif action in ("set_level","add_coins","unlock_themes"):
            uid=int(request.form.get("user_id",0))
            if action=="set_level":
                level=max(1,min(100,int(request.form.get("level",1))))
                xp=max(0,int(request.form.get("xp",level*100)))
                def set_level(fp): fp["level"]=level; fp["xp"]=max(xp,level*100-100); fp["developer"]=level>=100
                update_state(con,uid,set_level); message="Learner level and XP updated."
            elif action=="add_coins":
                amount=max(0,int(request.form.get("coins",0)))
                update_state(con,uid,lambda fp: fp.update(coins=int(fp.get("coins",0))+amount)); message="Coins added."
            else:
                def unlock_themes(fp):
                    fp["developer"]=True
                    fp["unlockedThemes"]=["classic","spider","barbie","bmw","gold","silver","galaxy","neon","batman","ironman","lambo","ferrari","minecraft","ocean","forest","sakura","royal","diamond","midnight","sunset","glacier","fire","nature","minimal","rgb","crystal","rainbow","bronze","milestone-silver","milestone-animated","legendary","cyberpunk","aurora","arctic-night","barbie-motion","bmw-night"]
                update_state(con,uid,unlock_themes); message="All themes unlocked for that learner."
        else: message="No action was performed."
    return redirect(url_for("admin",message=message))

@app.errorhandler(404)
def not_found(_): return "Page not found. Return to FluentPath.",404

if __name__=="__main__":
    init_db()
    app.run(debug=True)
