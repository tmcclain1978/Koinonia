from __future__ import annotations

import os, sys, time, json, logging, sqlite3
from pathlib import Path
from functools import wraps

# third-party
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, send_from_directory, abort
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from jinja2 import ChoiceLoader, FileSystemLoader
from apscheduler.schedulers.background import BackgroundScheduler
from auth_dao import (
    ensure_auth_schema,
    user_find_by_id,
    user_find_by_username,
    user_find_by_email,
    user_create,
)
ensure_auth_schema()

def _mask(v): 
    return bool(v), (v[:4] + "…" if v else None)

print("[BOOT] FMP_API_KEY present/masked:", _mask(os.getenv("FMP_API_KEY")))
print("[BOOT] POLYGON_API_KEY present/masked:", _mask(os.getenv("POLYGON_API_KEY")))

# --- Paths
BASE_DIR         = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LEGACY_TEMPLATES = BASE_DIR / "Legacy_flask" / "templates"
LEGACY_STATIC    = BASE_DIR / "Legacy_flask" / "static"
APP_STATIC       = BASE_DIR / "static"                      # site-wide static (e.g., charting.css/js)
FRONTEND_EXPORT = BASE_DIR / "out"                         # Next/Lovable static export
          
# --- Trading bot config (env) ---
ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
PAPER_MODE     = os.getenv("PAPER_MODE", "true").lower() == "true"
BOT_DEFAULT_INTERVAL_SEC = int(os.getenv("BOT_DEFAULT_INTERVAL_SEC", "60"))
BOT_MAX_SYMBOLS = int(os.getenv("BOT_MAX_SYMBOLS", "12"))          

FRONTEND_BUILD = FRONTEND_EXPORT

load_dotenv()  # loads C:\AI Advisor\.env into os.environ

print("[BOOT] FRONTEND_EXPORT exists:", FRONTEND_EXPORT.exists(), FRONTEND_EXPORT)

# If you want to hard-pin a Windows path, uncomment this (but prefer the relative one above)
# FRONTEND_BUILD = Path(r"C:\AI Advisor\frontend\dist")

app = Flask(__name__, static_folder=str(APP_STATIC))

# Boot prints to confirm paths
print("[BOOT] template_folder:", app.template_folder)
print("[BOOT] dashboard exists:", (LEGACY_TEMPLATES / "dashboard.html").exists(),
      LEGACY_TEMPLATES / "dashboard.html")
print("[BOOT] FRONTEND_BUILD exists:", FRONTEND_BUILD.exists(), FRONTEND_BUILD)

# Jinja can look in both legacy and future /templates
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(BASE_DIR / "templates")),
    FileSystemLoader(str(LEGACY_TEMPLATES)),
    app.jinja_loader,
])
scheduler = None  # global

def _start_scheduler_once():
    global scheduler
    if scheduler is None or not scheduler.running:
        scheduler = BackgroundScheduler(daemon=True)
        # Example job wiring (only if you actually have these funcs):
        # scheduler.add_job(my_periodic_task, 'interval', minutes=5, id='my_periodic_task', replace_existing=True)
        scheduler.start()

# Call this AFTER app is created and configured, but BEFORE app.run():
# Safe for both `flask run` and `python server.py`
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not os.environ.get("FLASK_DEBUG"):
    _start_scheduler_once()

def _has_template(name: str) -> bool:
    return (BASE_DIR / "templates" / name).exists()

def _serve_export_file(rel_path: str):
    abs_path = FRONTEND_EXPORT / rel_path
    if abs_path.exists():
        return send_from_directory(FRONTEND_EXPORT, rel_path)
    abort(404)

def require_ai_access(f):
    @wraps(f)
    def _wrap(*args, **kw):
        if not getattr(current_user, "is_authenticated", False):
            return jsonify({"detail": "Unauthorized"}), 401
        if getattr(current_user, "role", "user") != "admin" and not getattr(current_user, "can_use_ai", False):
            return jsonify({"detail": "Forbidden: AI access not enabled"}), 403
        return f(*args, **kw)
    return _wrap
# In-memory bot state (also returned by /status)
AI_BOT = {
    "running": False,
    "job_id": "ai_trading_bot_tick",
    "interval_sec": BOT_DEFAULT_INTERVAL_SEC,
    "symbols": ["AAPL", "MSFT", "NVDA", "SPY"],
    "last_run": None,
    "last_result": None,
}
def _ensure_trade_journal():
    conn = sqlite3.connect("signals.db")
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id TEXT,
          broker TEXT,
          account_id TEXT,
          symbol TEXT,
          right TEXT,
          strike REAL,
          expiry TEXT,
          side TEXT,
          qty INTEGER,
          entry_px REAL,
          setup TEXT,
          checklist_json TEXT,
          notes TEXT,
          opened_at TEXT
        );
        """)
        conn.commit()
    finally:
        conn.close()

_ensure_trade_journal()

from auth_dao import ensure_auth_schema, user_find_by_username, user_find_by_email, user_create
ensure_auth_schema()

#---------Login,Username--------------------

# ---------- Auth (SQLite + Flask-Login) ----------
# ---------- Auth (SQLite + Flask-Login) ----------

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


ADMIN_INVITE_CODE = os.getenv("ADMIN_INVITE_CODE", "")
USER_INVITE_CODE  = os.getenv("USER_INVITE_CODE",  "")

app.secret_key = app.secret_key or os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


def _row_to_user(row):
    if not row:
        return None
    # row is sqlite3.Row from _auth_db()
    return User(
        row["id"], row["username"], row["email"],
        row.get("role", "user"),
        row.get("can_use_ai", 1),
        row.get("can_trade_bot", 0),
    )

class UserSession(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.username = row["username"]
        self.email = row["email"]
        self.role = row["role"]
        self.can_use_ai = bool(row["can_use_ai"])
        self.can_trade_bot = bool(row["can_trade_bot"])

@login_manager.user_loader
def load_user(user_id: str):
    row = user_find_by_id(user_id)
    return UserSession(row) if row else None



# -------- Routes: Register / Login / Logout --------
# Start unauthenticated users at /login

@app.get("/login")
def login():
    if getattr(current_user, "is_authenticated", False):
        return redirect(url_for("dashboard") if "dashboard" in app.view_functions else url_for("advisor_template"))
    return render_template("login.html", next=request.args.get("next"), hide_nav=True)

@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or (url_for("dashboard") if "dashboard" in app.view_functions else url_for("advisor_template"))

    row = user_find_by_username(username)   # <-- was find_user_by_username
    if not row or not check_password_hash(row["pw_hash"], password):
        flash("Invalid username or password.", "danger")
        return redirect(url_for("login", next=nxt))

    user = UserSession(row)                 # or your session wrapper
    login_user(user, remember=True)
    flash(f"Welcome, {user.username}.", "success")
    return redirect(nxt)

@app.get("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("login"))

@app.get("/register")
def register():
    if getattr(current_user, "is_authenticated", False):
        return redirect(url_for("dashboard") if "dashboard" in app.view_functions else url_for("advisor_template"))
    return render_template("register.html", hide_nav=True)

@app.post("/register")
def register_post():
    username = (request.form.get("username") or "").strip()
    email    = (request.form.get("email") or "").strip() or None
    pw1      = request.form.get("password") or ""
    pw2      = request.form.get("confirm")  or ""
    invite   = (request.form.get("invite")  or "").strip()

    # Basic validation
    if not username or not pw1:
        flash("Username and password are required.", "danger")
        return redirect(url_for("register"))
    if " " in username:
        flash("Username cannot contain spaces.", "danger")
        return redirect(url_for("register"))
    if pw1 != pw2:
        flash("Passwords do not match.", "danger")
        return redirect(url_for("register"))
    if len(pw1) < 8:
        flash("Password must be at least 8 characters.", "danger")
        return redirect(url_for("register"))

    # Invitation codes => role/capabilities
    can_use_ai     = True           # both roles can see advisor UI
    can_trade_bot  = False          # only admins can use trading bot
    if ADMIN_INVITE_CODE and invite == ADMIN_INVITE_CODE:
        role = "admin"
        can_trade_bot = True
    elif USER_INVITE_CODE and invite == USER_INVITE_CODE:
        role = "user"
        can_trade_bot = False
    else:
        flash("Invalid invitation code.", "danger")
        return redirect(url_for("register"))

    # Uniqueness checks
    if user_find_by_username(username):
        flash("Username already exists.", "warning")
        return redirect(url_for("register"))
    if email and user_find_by_email(email):
        flash("An account with this email already exists.", "warning")
        return redirect(url_for("register"))

    # Create user
    try:
        user_create(username, email, pw1, role, can_use_ai, can_trade_bot)
        flash("Registration successful. Please sign in.", "success")
        return redirect(url_for("login"))
    except Exception as e:
        app.logger.exception("Registration failed")
        flash(f"Registration failed: {e}", "danger")
        return redirect(url_for("register"))
@app.get("/terms")
def terms():
    return render_template("terms.html")  # create a simple stub page

@app.get("/privacy")
def privacy():
    return render_template("privacy.html")
# ---------- Legacy pages & assets ----------
@app.route("/dashboard/static/<path:filename>", endpoint="dashboard_static")
def dashboard_static(filename: str):
    return send_from_directory(LEGACY_STATIC, filename)

# ---------- SPA (Vite) ----------
@app.route("/dashboard/advisor", endpoint="page_advisor", methods=["GET"])
def advisor_index():
    # SPA entry
    return send_from_directory(FRONTEND_BUILD, "index.html")

@app.route("/dashboard/advisor/<path:subpath>", endpoint="advisor_assets", methods=["GET"])
def advisor_catchall(subpath: str):
    # Prevent path traversal
    root = FRONTEND_BUILD.resolve()
    target = (FRONTEND_BUILD / subpath).resolve()
    if not str(target).startswith(str(root)):
        abort(404)

    # Serve real files (e.g. /assets/*.js, *.css, images)
    if target.is_file():
        rel = target.relative_to(root).as_posix()
        return send_from_directory(FRONTEND_BUILD, rel)

    # Otherwise this is an SPA client route (e.g., /dashboard/advisor/login)
    return send_from_directory(FRONTEND_BUILD, "index.html")

# Keep BASE_DIR on sys.path for relative imports
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

#----------Lovable---Website--------

def has_tpl(name: str) -> bool:
    return (BASE_DIR / "templates" / name).exists()

def serve_export(relpath: str):
    if not FRONTEND_EXPORT:
        return Response("Export folder not found. Put your Next export in ./out or ./Frontend/out", 500, {"Content-Type": "text/plain"})
    target = FRONTEND_EXPORT / relpath
    if target.exists():
        # relpath must be relative to export root
        return send_from_directory(FRONTEND_EXPORT, relpath)
    return Response(f"Missing export file: {target}", 404, {"Content-Type": "text/plain"})

@app.get("/", endpoint="home")
def home():
    # 1) Unauthenticated → Login
    if not getattr(current_user, "is_authenticated", False):
        return redirect(url_for("login"))

    # 2) Authenticated → app landing
    if "dashboard" in app.view_functions:
        return redirect(url_for("dashboard"))
    if "advisor_template" in app.view_functions:
        return redirect(url_for("advisor_template"))

    # 3) Fallbacks if no dashboard/advisor route
    tpl = BASE_DIR / "templates" / "home.html"
    if tpl.exists():
        return render_template("home.html")

    # requires your existing helper
    return _serve_export_file("index.html")

@app.get("/dashboard")
def dashboard():
    if has_tpl("dashboard.html"):
        return render_template("dashboard.html")
    return serve_export("dashboard/index.html")

@app.get("/compliance")
def compliance():
    if has_tpl("compliance.html"):
        return render_template("compliance.html")
    return serve_export("compliance/index.html")

@app.get("/verify")
def verify():
    if has_tpl("verify.html"):
        return render_template("verify.html")
    return serve_export("verify/index.html")

@app.get("/compliance/<userId>")
def compliance_user(userId):
    if has_tpl("compliance-userId.html"):
        return render_template("compliance-userId.html", userId=userId)
    # fallback to generic page if no templated version
    return serve_export("compliance/index.html")

@app.get("/advisor")
def advisor_template():
    return render_template("ai_advisor.html")

# Works on Flask 2.2+ with method shortcuts
@app.get("/analytics", endpoint="page_analytics")
@login_required
def page_analytics():
    return render_template("analytics.html")

# ---------- Exported asset routes (Next.js _next and common folders) ----------
@app.route("/_next/<path:asset>")
def next_asset(asset):
    return send_from_directory(FRONTEND_EXPORT / "_next", asset)

for _folder in ["assets","css","js","img","images","fonts","media","static"]:
    fp = FRONTEND_EXPORT / _folder
    if fp.exists():
        app.add_url_rule(
            f"/{_folder}/<path:path>",
            endpoint=f"export_{_folder}",
            view_func=lambda path, fp=fp: send_from_directory(fp, path),
            methods=["GET"],
        )

# --- Legacy dashboard API stubs to satisfy ai_advisor.js / audit.js ---

from flask import request, jsonify

@app.get("/api/ai_picks")
def api_ai_picks():
    # Return a tiny sample so the page can render something
    return jsonify({
        "picks": [
            {"symbol": "AAPL", "side": "BUY", "confidence": 0.71},
            {"symbol": "MSFT", "side": "SELL", "confidence": 0.58},
        ],
        "ts": int(time.time())
    })

@app.get("/api/audit/summary")
def api_audit_summary():
    # If you already wrote audit_write elsewhere, you can compute real counts.
    # For now: safe placeholders.
    return jsonify({
        "counts": {"orders": 0, "wins": 0, "losses": 0},
        "last": {"event": "init", "ts": int(time.time())}
    })

@app.get("/api/orders")
def api_orders():
    # Shape expected by audit.js: array or { orders: [...] } / { response: [...] }
    return jsonify({"orders": []})

@app.get("/api/positions")
def api_positions():
    return jsonify({"positions": []})

@app.get("/api/positions/risk")
def api_positions_risk():
    return jsonify({"maxRisk": 0, "exposure": 0, "notes": []})

@app.post("/api/order/cancel")
def api_order_cancel():
    payload = request.get_json(force=True) or {}
    # Normally you’d check Authorization and call broker adapter here.
    return jsonify({"ok": True, "action": "cancel", "order_id": payload.get("order_id")})

@app.post("/api/order/replace")
def api_order_replace():
    payload = request.get_json(force=True) or {}
    return jsonify({"ok": True, "action": "replace", "order_id": payload.get("order_id"), "order": payload.get("order")})
#-----Temporary Debug---------------

@app.get("/health")
def health():
    return "ok"

@app.get("/debug/urlmap")
def debug_urlmap():
    # list all routes
    lines = [str(r) for r in app.url_map.iter_rules()]
    return "<pre>" + "\n".join(lines) + "</pre>"

@app.get("/debug/fs")
def debug_fs():
    p = FRONTEND_EXPORT
    exists = p.exists()
    listing = "\n".join(str(x.name) for x in (p.iterdir() if exists else []))
    return f"FRONTEND_EXPORT: {p}\nexists: {exists}\n\n{listing}", 200, {"Content-Type": "text/plain"}

# ---------------- App & config ----------------
app.config["SECRET_KEY"] = os.getenv("APP_SECRET", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Ensure local folders exist (Windows-friendly)
os.makedirs("data", exist_ok=True)
os.makedirs(os.getenv("SCHWAB_TOKEN_PATH", ".tokens"), exist_ok=True)

# Option B: if you have extensions.py with `db = SQLAlchemy()`,
# comment Option A above and uncomment below:

from extensions import db
db.init_app(app)

@app.context_processor
def inject_nav():
    # Top-level pages (mix legacy + new)
    nav_items = [
        {"label": "Home",      "href": url_for("home")},
        {"label": "Dashboard", "href": url_for("dashboard")},
        {"label": "Advisor",   "href": url_for("page_advisor")},   # SPA route you already have
        {"label": "Education", "href": "/education"},              # legacy routes from your URL map
        {"label": "Podcast",   "href": "/podcast"},
        {"label": "Admin",     "href": "/admin"},
    ]
    # “Templates” dropdown (add whatever you want here)
    template_items = [
        {"label": "Compliance", "href": url_for("compliance")},
        {"label": "Verify",     "href": url_for("verify")},
        # add more template pages as needed
    ]
    def is_active(href: str) -> bool:
        return request.path == href or (href != "/" and request.path.startswith(href))
    return {"NAV_ITEMS": nav_items, "TEMPLATE_ITEMS": template_items, "is_active": is_active}

@app.context_processor
def nav_helpers():
    def href_for(endpoint, default_path='/', **values):
        try:
            return url_for(endpoint, **values)
        except Exception:
            return default_path
    return dict(href_for=href_for)


# ---------------- Globals/Paths ----------------
AUDIT_PATH = os.getenv("TRADE_AUDIT_PATH", os.path.join("data", "trade_audit.jsonl"))

# ---------------- Blueprints (import AFTER app is created) ----------------
from candle_routes import candle_routes
from engine.datasources.integrations.schwab_adapter import SchwabClient, fetch_features
from ai.sandbox import sandbox_bp

app.register_blueprint(candle_routes, url_prefix="/api/candles")
app.register_blueprint(sandbox_bp,    url_prefix="/api/sandbox")

# ---------------- Scheduler (for MOC/LOC helper) ----------------
from pytz import timezone
EASTERN = timezone("US/Eastern")

def audit_write(event: str, payload: dict):
    """Lightweight audit appender."""
    try:
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "event": event, **payload}) + "\n")
    except Exception:
        pass

def _schedule_close_submit(uid: str, account_id: str, normalized: dict, *, paper_mode: bool):
    """
    Schedule a near-close submission:
      - MOC -> MARKET at 15:59:50 ET
      - LOC -> LIMIT (price=normalized.locPrice) at 15:59:50 ET
    Paper mode audits only; live mode submits via Schwab.
    """
    now = datetime.now(EASTERN)
    target = now.replace(hour=15, minute=59, second=50, microsecond=0)
    if now >= target:
        target = (now + timedelta(days=1)).replace(hour=15, minute=59, second=50, microsecond=0)
    while target.weekday() >= 5:  # 5=Sat, 6=Sun
        target += timedelta(days=1)

    job_id = f"close_{uid}_{int(time.time())}"

    def _job():
        try:
            final_type = "MARKET" if (normalized.get("orderType","").upper() == "MOC") else "LIMIT"
            payload = {**normalized, "orderType": final_type}
            if final_type == "LIMIT":
                payload["price"] = normalized.get("locPrice")

            if paper_mode:
                audit_write("order.close.paper.submit", {
                    "account": account_id, "normalized": normalized,
                    "final_payload": payload, "status": "SUBMITTED"
                })
                return

            from server import map_to_schwab_order  # import here to avoid top-level cycles if any
            spec = map_to_schwab_order(payload)
            c = SchwabClient(uid)
            resp = c.place_order(account_id, spec)
            audit_write("order.close.live.submit", {
                "account": account_id, "normalized": normalized, "spec": spec, "resp": resp
            })
        except Exception as e:
            audit_write("order.close.error", {"normalized": normalized, "error": str(e)})

    _sched.add_job(_job, 'date', run_date=target, id=job_id)
    return {"job_id": job_id, "scheduled_for": target.isoformat()}
# ---- end header ----

# -----------------------------
# Admin helpers
# -----------------------------

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = session.get("username", "").lower()
        try:
            with open("admin_users.txt", "r") as f:
                admins = [line.strip().lower() for line in f if line.strip()]
        except FileNotFoundError:
            admins = []

        if username not in admins:
            flash("⚠️ Admin access only.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function


def is_admin_user(username: str) -> bool:
    try:
        with open("admin_users.txt", "r") as f:
            admins = [line.strip().lower() for line in f if line.strip()]
    except FileNotFoundError:
        admins = []
    return username.lower() in admins


# -----------------------------
# Flask app & DB
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)     # ensure folder exists

DB_PATH = DATA_DIR / "app.db"                   # -> C:/AI Advisor/data/app.db
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("APP_SECRET", "dev-secret")


from models import User

from sqlalchemy import text

def bootstrap_db():
    with app.app_context():
        db.create_all()  # <-- the ONE place we create tables

        # (optional) schema tweaks; example for ml_predictions
        # existing_cols = {row[1] for row in db.session.execute(text("PRAGMA table_info(ml_predictions)"))}
        # for name, coltype in [("pattern","TEXT"),("pattern_conf","REAL"),("final_confidence","REAL")]:
        #     if name not in existing_cols:
        #         db.session.execute(text(f"ALTER TABLE ml_predictions ADD COLUMN {name} {coltype}"))
        # db.session.commit()

# Run on demand via CLI: `flask bootstrap-db`
import click
@app.cli.command("bootstrap-db")
def bootstrap_db_cli():
    bootstrap_db()
    click.echo("DB bootstrap complete.")

# Or run automatically in dev by setting INIT_DB_ON_STARTUP=true in .env
if os.getenv("INIT_DB_ON_STARTUP","false").lower() == "true":
    bootstrap_db()

# -----------------------------
# Schwab OAuth + Trader API
# -----------------------------
SCHWAB_CLIENT_ID   = os.getenv("SCHWAB_CLIENT_ID", "")
SCHWAB_CLIENT_SECRET = os.getenv("SCHWAB_CLIENT_SECRET", "")
SCHWAB_REDIRECT_URI  = os.getenv("SCHWAB_REDIRECT_URI", "http://localhost:5000/auth/schwab/callback")
SCHWAB_AUTH_BASE   = os.getenv("SCHWAB_AUTH_BASE", "https://signin.schwab.com").rstrip("/")
SCHWAB_API_BASE    = os.getenv("SCHWAB_API_BASE", "https://api.schwab.com").rstrip("/")
SCHWAB_SCOPES      = (os.getenv("SCHWAB_SCOPES") or "traderapi").split()

ENABLE_TRADING = os.getenv("ENABLE_TRADING", "false").lower() == "true"
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
MAX_ORDER_QTY = int(os.getenv("MAX_ORDER_QTY", 5))

with app.app_context():
    pass
  
# -----------------------------
# Existing endpoints (expected move, bracket, scanner, journal, etc.) remain below...
# -----------------------------
# providers.py

FMP_KEY = os.getenv("FMP_API_KEY")
POLY_KEY = os.getenv("POLYGON_API_KEY")

def fmp_quote(symbols):
    # FMP batched quote
    url = "https://financialmodelingprep.com/api/v3/quote/" + ",".join(symbols)
    r = requests.get(url, params={"apikey": FMP_KEY}, timeout=10)
    r.raise_for_status()
    return r.json()

def polygon_aggs(symbol, timespan="day", limit=5):
    # Polygon recent aggregates
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/{timespan}/2024-01-01/2024-12-31"
    r = requests.get(url, headers={"X-Polygon-API-Key": POLY_KEY}, timeout=10, params={"limit": limit, "adjusted":"true"})
    r.raise_for_status()
    return r.json()


# -----------------------------
# --- AI Options Bot dependencies & helpers -------------------------------
from typing import Optional, List, Dict, Any

# .env keys (make sure you called load_dotenv() at top of server.py)
FMP_API_KEY = os.getenv("FMP_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

def _mask(v): 
    return bool(v), (v[:4]+"…"+v[-2:] if v and len(v) > 6 else v)

print("[AI] FMP key present/masked:", _mask(FMP_API_KEY))
print("[AI] Polygon key present/masked:", _mask(POLYGON_API_KEY))

def _quote_last(symbol: str) -> Optional[float]:
    """Return latest price using Polygon → FMP → (optional) local Schwab quote proxy."""
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return None

    # 1) Polygon (aggregates v2, last close or latest trade)
    if POLYGON_API_KEY:
        try:
            # Try last trade price
            r = requests.get(
                f"https://api.polygon.io/v2/last/trade/{symbol}",
                headers={"X-Polygon-API-Key": POLYGON_API_KEY},
                timeout=5,
            )
            if r.ok:
                t = r.json().get("results") or r.json()
                px = t.get("price") or t.get("p")  # polygon may use price 'p'
                if px:
                    return float(px)
        except Exception as e:
            logging.debug("Polygon last trade failed: %r", e)

        try:
            # Fallback: previous close
            r = requests.get(
                f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                headers={"X-Polygon-API-Key": POLYGON_API_KEY},
                timeout=5,
            )
            if r.ok and r.json().get("results"):
                return float(r.json()["results"][0]["c"])
        except Exception as e:
            logging.debug("Polygon prev close failed: %r", e)

    # 2) FMP (batch quote endpoint)
    if FMP_API_KEY:
        try:
            r = requests.get(
                f"https://financialmodelingprep.com/api/v3/quote/{symbol}",
                params={"apikey": FMP_API_KEY},
                timeout=5,
            )
            if r.ok and isinstance(r.json(), list) and r.json():
                px = r.json()[0].get("price") or r.json()[0].get("previousClose")
                if px:
                    return float(px)
        except Exception as e:
            logging.debug("FMP quote failed: %r", e)

    # 3) Optional: your own quotes proxy (Schwab) if exposed server-side
    #    Uncomment if you have this route implemented.
    # try:
    #     r = requests.post(
    #         "http://127.0.0.1:5000/api/schwab/quotes",
    #         json={"symbols": [symbol]},
    #         timeout=5,
    #     )
    #     if r.ok:
    #         data = r.json()
    #         if isinstance(data, dict):
    #             q = (data.get("quotes") or {}).get(symbol) or {}
    #             px = q.get("lastPrice") or q.get("last") or q.get("mark")
    #             if px:
    #                 return float(px)
    # except Exception as e:
    #     logging.debug("Local Schwab quote failed: %r", e)

    return None

# -----------------------------
# ---- Engine glue (use your real engine in /engine) ----------------------
# Make sure BASE_DIR is on sys.path above this, e.g.:
# if str(BASE_DIR) not in sys.path: sys.path.insert(0, str(BASE_DIR))

# engine-backed suggestion (no AIEngine class)
from engine.suggest import suggest_for_symbol  # C:\AI Advisor\engine\suggest.py

def _engine_side_conf(symbol: str) -> Optional[dict]:
    """
    Normalize your engine output to {"side","confidence","suggestion"} for reuse.
    """
    try:
        s = suggest_for_symbol(symbol)  # returns rich dict
        strat = (s.get("strategy") or "").lower()
        if any(k in strat for k in ("call", "debit")):
            side = "BUY"
        elif any(k in strat for k in ("put", "credit")):
            side = "SELL"
        else:
            side = "BUY"
        ctx = s.get("context") or {}
        conf = ctx.get("score") or ctx.get("edge") or 0.65
        try: conf = float(conf)
        except: conf = 0.65
        return {"side": side, "confidence": conf, "suggestion": s}
    except Exception as e:
        logging.debug("suggest_for_symbol error for %s: %r", symbol, e)
        return None

# NOTE: _quote_last(symbol) must be defined elsewhere (Polygon/FMP fallback).
# If you don't have it yet, ask me and I'll paste the version that tries
# Polygon then FMP with your .env keys.

# -----------------------------
# AI Options Bot (adapts engine signals → option suggestions)
# -----------------------------
OPT_DEFAULT_DTE   = int(os.getenv("OPT_DEFAULT_DTE", 1))
OPT_TARGET_DELTA  = float(os.getenv("OPT_TARGET_DELTA", 0.30))
OPT_DEFAULT_QTY   = int(os.getenv("OPT_DEFAULT_QTY", 1))
OPT_ENABLE_STAGE  = os.getenv("OPT_ENABLE_STAGE", "false").lower() == "true"
PAPER_MODE        = os.getenv("PAPER_MODE", "true").lower() == "true"  # you already inject via context

class OptionsAIBot:
    def __init__(self, symbols: List[str]): self.symbols = symbols

    def _signal_for(self, sym: str):
        sig = _engine_side_conf(sym)
        if sig: return sig
        last = _quote_last(sym)
        if last is None: return None
        side = "BUY" if int(time.time()) % 2 == 0 else "SELL"
        return {"side": side, "confidence": 0.55, "suggestion": None}

    def _select_contract(self, last: float, side: str, dte: int, target_delta: float):
        otm_pct = 0.04 if target_delta <= 0.35 else 0.02
        if side == "BUY":
            right, strike = "CALL", round(last * (1 + otm_pct), 2)
        else:
            right, strike = "PUT",  round(last * (1 - otm_pct), 2)
        return {"right": right, "strike": strike, "expiry_hint": f"+{dte}d", "target_delta": target_delta}

    def suggestions(self, dte=None, target_delta=None, qty=None):
        dte = dte or OPT_DEFAULT_DTE
        target_delta = target_delta or OPT_TARGET_DELTA
        qty = qty or OPT_DEFAULT_QTY
        out = []
        for sym in self.symbols:
            sig = self._signal_for(sym)
            if not sig: continue
            last = _quote_last(sym)
            if last is None: continue
            side = sig["side"].upper()
            conf = float(sig.get("confidence", 0.5))
            sel  = self._select_contract(last, side, dte, target_delta)
            out.append({
                "symbol": sym,
                "underlying_last": last,
                "direction": side,
                "confidence": round(conf, 3),
                "order": {"right": sel["right"], "strike": sel["strike"], "expiry": sel["expiry_hint"], "qty": qty},
                "selection": {"method": "engine+heuristic", "target_delta": sel["target_delta"]},
                "engine": sig.get("suggestion")
            })
        return out

# Instantiate with your default watchlist
options_ai_bot = OptionsAIBot(["AAPL","MSFT","NVDA","SPY"])

@app.route("/api/ai/options/signals")
@login_required
def api_ai_options_signals():
    try:
        dte     = request.args.get("dte",   type=int)   or OPT_DEFAULT_DTE
        tdelta  = request.args.get("delta", type=float) or OPT_TARGET_DELTA
        qty     = request.args.get("qty",   type=int)   or OPT_DEFAULT_QTY

        # Allow ?symbols=AAPL,MSFT
        syms_arg = (request.args.get("symbols") or "").replace(" ", "")
        symbols = [s for s in syms_arg.split(",") if s] or options_ai_bot.symbols

        # Run ideas for the requested list
        bot = OptionsAIBot(symbols)
        ideas = bot.suggestions(dte=dte, target_delta=tdelta, qty=qty)

        # Optional: auto-stage (paper only)
        staged = []
        if OPT_ENABLE_STAGE and PAPER_MODE and ideas:
            conn = sqlite3.connect("signals.db")
            try:
                cur = conn.cursor()
                for idea in ideas:
                    ord_ = idea["order"]
                    cur.execute(
                        """
                        INSERT INTO trade_journal(user_id, broker, account_id, symbol, right, strike, expiry, side, qty,
                                                  entry_px, setup, checklist_json, notes, opened_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                        """,
                        (
                            getattr(current_user, "id", None) or current_user.get_id() or "",
                            "schwab", "", idea["symbol"], ord_["right"], ord_["strike"], ord_["expiry"],
                            "BUY", ord_["qty"], idea["underlying_last"], "AI_options_v1",
                            json.dumps({"conf": idea["confidence"]}), "staged by AI"
                        )
                    )
                    staged.append({"symbol": idea["symbol"], "order": ord_})
                conn.commit()
            finally:
                conn.close()

        return jsonify({"ideas": ideas, "staged": staged, "paper_mode": PAPER_MODE, "auto_stage": OPT_ENABLE_STAGE})
    except Exception as e:
        logging.exception("api_ai_options_signals failed")
        return jsonify({"detail": str(e)}), 500

@app.route("/api/ai/options/config", methods=["POST"])
@login_required
def api_ai_options_config():
    body = request.get_json(silent=True) or {}
    global OPT_DEFAULT_DTE, OPT_TARGET_DELTA, OPT_DEFAULT_QTY
    if "dte" in body:   OPT_DEFAULT_DTE   = max(0, int(body["dte"]))
    if "delta" in body: OPT_TARGET_DELTA  = max(0.05, min(0.95, float(body["delta"])))
    if "qty" in body:   OPT_DEFAULT_QTY   = max(1, int(body["qty"]))
    return jsonify({"dte": OPT_DEFAULT_DTE, "delta": OPT_TARGET_DELTA, "qty": OPT_DEFAULT_QTY})

#-------Quote Helper--------------

FMP_API_KEY = os.getenv("FMP_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

def _quote_last(symbol: str):
    s = (symbol or "").upper().strip()
    if not s: return None
    # Polygon last trade
    if POLYGON_API_KEY:
        try:
            r = requests.get(f"https://api.polygon.io/v2/last/trade/{s}",
                             headers={"X-Polygon-API-Key": POLYGON_API_KEY}, timeout=5)
            if r.ok:
                j = r.json().get("results") or r.json()
                px = j.get("price") or j.get("p")
                if px: return float(px)
        except Exception as e:
            logging.debug("polygon last trade failed: %r", e)
        try:
            r = requests.get(f"https://api.polygon.io/v2/aggs/ticker/{s}/prev",
                             headers={"X-Polygon-API-Key": POLYGON_API_KEY}, timeout=5)
            if r.ok and r.json().get("results"):
                return float(r.json()["results"][0]["c"])
        except Exception as e:
            logging.debug("polygon prev close failed: %r", e)
    # FMP quote
    if FMP_API_KEY:
        try:
            r = requests.get(f"https://financialmodelingprep.com/api/v3/quote/{s}",
                             params={"apikey": FMP_API_KEY}, timeout=5)
            if r.ok and isinstance(r.json(), list) and r.json():
                px = r.json()[0].get("price") or r.json()[0].get("previousClose")
                if px: return float(px)
        except Exception as e:
            logging.debug("fmp quote failed: %r", e)
    return None


# ---------- HTML routes ----------
@app.route("/advisor")
@login_required
def advisor():
    # If you're already using /dashboard as the main page, you can alias or
    # point this to a more advisor-centric template. For now we reuse dashboard.html:
    return render_template("dashboard.html", admin_token=os.getenv("ADMIN_API_TOKEN", ""))

@app.route("/audit")
def audit():
    return render_template("audit.html")

# legacy alias expected by templates
app.add_url_rule("/audit", endpoint="page_audit", view_func=audit)

@app.route("/education", endpoint="page_education")
def education():
    return render_template("education.html")

@app.route("/podcast", endpoint="page_podcast")
def podcast():
    return render_template("podcast.html")

# Admin-only pages (only linked from admin UI)

# Admin: Education
@app.route("/admin/education", endpoint="page_admin_education")
def page_admin_education_view():
    return render_template("admin_education.html", admin_token=os.getenv("ADMIN_API_TOKEN",""))

# Admin: Podcast
@app.route("/admin/podcast", endpoint="page_admin_podcast")
def page_admin_podcast_view():
    return render_template("admin_podcast.html", admin_token=os.getenv("ADMIN_API_TOKEN",""))

# Admin: Bot Control
@app.route("/admin/bot", endpoint="page_admin_bot")
def page_admin_bot_view():
    return render_template("admin_bot.html", admin_token=os.getenv("ADMIN_API_TOKEN",""))

# --- Paper trading (Route B: plural filename) ---
@app.route("/trade/orders")
@login_required
def trade_orders():
    return render_template(
        "trade_orders.html",
        admin_token=os.getenv("ADMIN_API_TOKEN", "")
    )
app.add_url_rule("/trade/orders", endpoint="page_trade_orders", view_func=trade_orders)

# Admin hub (legacy admin.html)
@app.route("/admin", endpoint="page_admin_home")
def page_admin_home():
    return render_template("admin.html", admin_token=os.getenv("ADMIN_API_TOKEN",""))

# ---------- Schwab Admin: helpers ----------
TOKEN_DIR = os.getenv("SCHWAB_TOKEN_PATH", ".tokens")

def _token_path(uid: str) -> str:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{uid}.json")

def _read_token_meta(uid: str):
    """Return best-effort token metadata for the given user."""
    path = _token_path(uid)
    if not os.path.exists(path):
        return {"exists": False}
    meta = {"exists": True, "path": path}
    try:
        with open(path, "r", encoding="utf-8") as f:
            tok = json.load(f)
        meta["raw"] = {k: ("***" if "token" in k else v) for k, v in tok.items()}
        # common fields if your adapter saved them
        access = tok.get("access_token")
        refresh = tok.get("refresh_token")
        meta["has_access"] = bool(access)
        meta["has_refresh"] = bool(refresh)
        # expiry hints
        exp_at = tok.get("access_expires_at") or tok.get("expires_at")
        now = time.time()
        if exp_at:
            meta["access_expires_at"] = exp_at
            meta["access_ttl_sec"] = int(exp_at - now)
        # file system fallback timestamps
        stat = os.stat(path)
        meta["file_ctime"] = int(stat.st_ctime)
        meta["file_mtime"] = int(stat.st_mtime)
    except Exception as e:
        meta["error"] = str(e)
    return meta

# ---------- Schwab Admin APIs ----------
@app.get("/api/schwab/admin/token")
@login_required
def schwab_admin_token():
    uid = getattr(current_user, "id", "demo-user")
    return jsonify(_read_token_meta(uid))

@app.post("/api/schwab/admin/refresh")
@login_required
def schwab_admin_refresh():
    uid = getattr(current_user, "id", "demo-user")
    try:
        c = SchwabClient(uid)
        # ensure_token() in your adapter refreshes when near expiry;
        # if you added a 'force' flag, pass it; otherwise, call a quotes ping to force refresh path.
        c.ensure_token()  # refresh if needed
        # cheap ping to guarantee we have a good token after refresh
        try:
            c.price_history("SPY", period="1D", interval="1d")
        except Exception:
            pass
        return jsonify({"ok": True, "message": "Refreshed (if needed).", "token": _read_token_meta(uid)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/schwab/admin/delete")
@login_required
def schwab_admin_delete():
    uid = getattr(current_user, "id", "demo-user")
    path = _token_path(uid)
    try:
        if os.path.exists(path):
            os.remove(path)
        return jsonify({"ok": True, "message": f"Deleted token {path}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# Pass-through to build the authorize URL you already have:
@app.get("/api/schwab/admin/login_url")
@login_required
def schwab_admin_login_url():
    # reuse the same handler you use at /api/schwab/auth/login, or rebuild here if you prefer.
    try:
        # If you already have /api/schwab/auth/login that returns {"url": ...},
        # you can proxy-call it from the client instead. Here we just rebuild using the adapter:
        c = SchwabClient(getattr(current_user, "id", "demo-user"))
        return jsonify({"url": c.build_authorize_url()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Schwab Setup page ----------
@app.route("/admin/schwab")
@login_required
def admin_schwab():
    # Surface envs for quick visual checks (no secrets rendered)
    env = {
        "SCHWAB_CLIENT_ID": os.getenv("SCHWAB_CLIENT_ID", ""),
        "SCHWAB_REDIRECT_URI": os.getenv("SCHWAB_REDIRECT_URI", ""),
        "SCHWAB_API_URL": os.getenv("SCHWAB_API_URL", os.getenv("SCHWAB_API_BASE", "")),
        "SCHWAB_AUTH_URL": os.getenv("SCHWAB_AUTH_URL", os.getenv("SCHWAB_AUTH_BASE", "")),
        "SCHWAB_TOKEN_URL": os.getenv("SCHWAB_TOKEN_URL", ""),
        "SCHWAB_SCOPES": os.getenv("SCHWAB_SCOPES", "marketdata trading read write"),
        "SCHWAB_TOKEN_PATH": TOKEN_DIR,
    }
    return render_template("admin_schwab_setup.html", env=env)

app.add_url_rule("/admin/schwab", endpoint="page_admin_schwab", view_func=admin_schwab)

# ---------- Audit helpers ----------
def _ensure_audit_file():
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    if not os.path.exists(AUDIT_PATH):
        open(AUDIT_PATH, "a").close()

def audit_write(event_type: str, payload: dict):
    """
    Use this from your AI and order routes.
    Example: audit_write("proposal", {...}); audit_write("order", {...})
    """
    _ensure_audit_file()
    record = {
        "ts": time.time(),
        "event": event_type,
        "user": getattr(current_user, "id", None),
        **payload,
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")

def audit_read(offset: int = 0, limit: int = 100):
    _ensure_audit_file()
    # simple tail-style read
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    total = len(lines)
    # newest first
    lines = lines[::-1]
    chunk = lines[offset: offset + limit]
    return [json.loads(x) for x in chunk], total

# --- helpers (put near your other helpers) ---
def _payoff_intrinsic(side: str, strike: float, S: float) -> float:
    """side: 'CALL' or 'PUT' -> intrinsic value at expiration (per share)."""
    if side == "CALL":
        return max(0.0, S - strike)
    return max(0.0, strike - S)

def _net_debit_credit(legs):
    """Positive = net debit paid; negative = net credit received."""
    net = 0.0
    for leg in legs:
        # BUY consumes cash (+price), SELL collects cash (-price)
        sign = +1 if leg.get("action","BUY").upper() == "BUY" else -1
        net += sign * float(leg.get("price", 0.0))
    return net

def _width_if_vertical(legs):
    """Assumes two legs, same expiry, same side; returns strike width (abs)."""
    if len(legs) != 2: return 0.0
    try:
        return abs(float(legs[0]["strike"]) - float(legs[1]["strike"]))
    except Exception:
        return 0.0

def _pl_expiration(symbol: str, legs, S: float, qty: int) -> float:
    """P/L at expiration for multi/single-leg using provided entry leg prices."""
    # intrinsic sum per share
    intrinsic_sum = 0.0
    for leg in legs:
        side = leg["side"].upper()  # CALL/PUT
        strike = float(leg["strike"])
        intrinsic = _payoff_intrinsic(side, strike, S)
        # BUY gains intrinsic, SELL loses intrinsic
        mult = +1 if leg.get("action","BUY").upper() == "BUY" else -1
        intrinsic_sum += mult * intrinsic
    # entry cost per share (net debit positive, credit negative)
    net = _net_debit_credit(legs)
    # per contract multiplier 100
    return (intrinsic_sum - net) * 100.0 * qty

def _spread_stats(legs):
    """Return maxProfit/maxLoss for verticals; for singles returns None."""
    if len(legs) != 2: return None
    s = legs[0]["side"].upper()
    same_side = s == legs[1]["side"].upper()
    same_exp = legs[0]["expiration"] == legs[1]["expiration"]
    if not (same_side and same_exp): return None
    width = _width_if_vertical(legs)
    net = _net_debit_credit(legs)  # debit>0, credit<0
    if net >= 0:  # debit spread
        return {"type":"debit", "width": width, "net": net,
                "maxLoss": net * 100, "maxProfit": (width - net) * 100}
    else:        # credit spread
        cr = -net
        return {"type":"credit","width": width, "net": net,
                "maxLoss": (width - cr) * 100, "maxProfit": cr * 100}

def _ndist_cdf(x: float) -> float:
    # Φ(x) using error function
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# --- Black–Scholes (no dividends, r≈0) ---
def _bs_price(S: float, K: float, T_years: float, sigma: float, call_put: str) -> float:
    if S <= 0 or K <= 0 or T_years <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T_years) / (sigma * math.sqrt(T_years))
    d2 = d1 - sigma * math.sqrt(T_years)
    if call_put.upper() == "CALL":
        return S * _ndist_cdf(d1) - K * _ndist_cdf(d2)
    else:
        return K * _ndist_cdf(-d2) - S * _ndist_cdf(-d1)

def _annualized_hv(closes: list[float]) -> float:
    if not closes or len(closes) < 22:
        return 0.0
    rets = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)

def _ema(vals: list[float], span: int) -> list[float]:
    if not vals: return []
    a = 2 / (span + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out

def _rsi(vals: list[float], period: int = 14) -> float:
    if len(vals) < period + 1: return 50.0
    diffs = [vals[i] - vals[i-1] for i in range(1, len(vals))]
    gains = [max(0, d) for d in diffs]; losses = [max(0, -d) for d in diffs]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def _features_from_window(window: list[dict]) -> dict:
    # window: list of candle dicts with 'close','high','low'
    closes = [c["close"] for c in window]
    ema9  = _ema(closes, 9)[-1]
    ema20 = _ema(closes, 20)[-1] if len(closes) >= 20 else closes[-1]
    rsi14 = _rsi(closes, 14)
    ret1  = (closes[-1] / closes[-2] - 1.0) if len(closes) > 1 else 0.0
    return {"ema9": ema9, "ema20": ema20, "rsi14": rsi14, "ret1": ret1}

# ---------- Audit API ----------
@app.get("/api/audit")
@login_required
def api_audit_list():
    try:
        offset = int(request.args.get("offset", "0"))
        limit  = int(request.args.get("limit", "100"))
    except ValueError:
        return {"error": "bad offset/limit"}, 400
    items, total = audit_read(offset=offset, limit=limit)
    return {"total": total, "offset": offset, "limit": limit, "items": items}

@app.get("/api/audit/download.csv")
@login_required
def api_audit_download_csv():
    _ensure_audit_file()
    # convert JSONL -> CSV (basic flatten)
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if not rows:
        return Response("", mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=audit.csv"})
    # collect headers
    headers = sorted({k for r in rows for k in r.keys()})
    buf = io.StringIO()
    buf.write(",".join(headers) + "\n")
    for r in rows:
        buf.write(",".join([json.dumps(r.get(h, "")) for h in headers]) + "\n")
    buf.seek(0)
    return Response(buf.read(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=audit.csv"})

# Paper trading (public)
@app.get("/paper/options", endpoint="page_paper_options")
def page_paper_options_view():
    return render_template("paper_options.html")

# --- JSON for analytics charts (replace with real data source) ---
@app.get("/api/options/analytics_stats")
@login_required
def api_options_analytics_stats():
    # TODO: compute from your audit DB
    return {
        "total": 120, "wins": 70, "losses": 50, "win_rate": 58.3, "avg_confidence": 92.1,
        "daily": {"labels": ["Mon","Tue","Wed","Thu","Fri"], "win_rate": [55,60,52,63,61]},
        "confidence": {"labels": ["80–85","85–90","90–95","95–100"], "values":[5,18,52,45]},
        "strategy_mix": {"Long Call":48, "Long Put":32, "Vertical":30, "Covered Call":10},
        "pnl": {"labels": ["D1","D2","D3","D4","D5"], "values":[0,150,-50,220,310]}
    }

# --- Paper trading APIs (replace with your simulator / audit) ---
from collections import deque
_paper_log = deque(maxlen=500)
_paper_eq  = 0.0

@app.post("/api/paper/options/simulate")
@login_required
def api_paper_sim():
    global _paper_eq
    order = request.get_json(force=True)
    # naive P/L sim
    import random; win = random.random() < 0.58
    pl = (random.uniform(40,120) if win else -random.uniform(40,120))
    _paper_eq += pl
    rec = {"ts": time.time(), "symbol":order["symbol"], "side":order["side"],
           "exp":order["expiration"], "strike":order["strike"], "qty":order["quantity"],
           "result": "win" if win else "loss", "pl": round(pl,2)}
    _paper_log.append(rec)
    # also write to your audit if you want:
    # audit_write("paper.sim", rec)
    return {"message":"Simulated","record":rec}

@app.get("/api/paper/options/stats")
@login_required
def api_paper_stats():
    wins = sum(1 for r in _paper_log if r["result"]=="win")
    losses = sum(1 for r in _paper_log if r["result"]=="loss")
    total = wins + losses
    wr = (wins/total*100) if total else 0.0
    labels = [f'#{i+1}' for i,_ in enumerate(_paper_log)]
    values = list(_accumulate([r["pl"] for r in _paper_log]))
    return {
        "total": total, "wins": wins, "losses": losses,
        "win_rate": wr, "avg_confidence": 92.0,  # replace with real
        "equity": {"labels": labels, "values": values}
    }

@app.get("/api/paper/options/log")
@login_required
def api_paper_log():
    limit = int(request.args.get("limit","50"))
    items = list(_paper_log)[-limit:]
    # newest first for UI readability
    items = items[::-1]
    return {"items": items, "total": len(_paper_log)}

@app.get("/api/paper/options/export.csv")
@login_required
def api_paper_export():
    import csv
    si = io.StringIO()
    w = csv.DictWriter(si, fieldnames=["ts","symbol","side","exp","strike","qty","result","pl"])
    w.writeheader()
    for r in _paper_log:
        w.writerow(r)
    si.seek(0)
    return Response(si.read(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=paper_options.csv"})

def _accumulate(seq):
    tot = 0.0
    for x in seq:
        tot += float(x or 0.0)
        yield round(tot,2)

@app.post("/api/sandbox/start")
@login_required
def sandbox_start():
    """
    Body: {symbol, period, interval, expiry_days, policy, step}
    step = bars until exit (e.g., 30 for ~30 minutes if interval=1m)
    """
    data = request.get_json(force=True)
    symbol  = data.get("symbol", "AAPL").upper()
    period  = data.get("period", "5D")
    interval = data.get("interval", "1m")
    expiry_days = int(data.get("expiry_days", 7))
    policy  = data.get("policy", "rule")  # "rule" or "model"
    step    = int(data.get("step", 30))

    session_id = uuid.uuid4().hex[:12]
    out_dir = os.path.join(_SANDBOX_DIR, f"{session_id}_{symbol}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    _ensure_dir(out_dir)
    _sandbox_sessions[session_id] = {"status": "queued", "progress": 0, "total": 0, "summary": {}, "out_dir": out_dir}

    # run in a thread so UI can poll
    t = threading.Thread(target=_run_sandbox, args=(session_id,),
                         kwargs={"symbol": symbol, "period": period, "interval": interval,
                                 "expiry_days": expiry_days, "policy": policy, "step": step}, daemon=True)
    t.start()
    return {"session_id": session_id, "status": "started"}

@app.get("/api/sandbox/status")
@login_required
def sandbox_status():
    sid = request.args.get("session_id")
    if not sid or sid not in _sandbox_sessions:
        return {"error": "unknown session"}, 404
    s = _sandbox_sessions[sid]
    # hide absolute paths from client; expose downloadable endpoints
    pub = dict(s)
    if "summary" in pub:
        summ = dict(pub["summary"])
        if "jsonl" in summ:
            summ["jsonl_url"] = f"/api/sandbox/download?session_id={sid}&fmt=jsonl"
            summ.pop("jsonl", None)
        if "csv" in summ:
            summ["csv_url"] = f"/api/sandbox/download?session_id={sid}&fmt=csv"
            summ.pop("csv", None)
        pub["summary"] = summ
    return pub

@app.get("/api/sandbox/download")
@login_required
def sandbox_download():
    sid = request.args.get("session_id"); fmt = request.args.get("fmt","jsonl")
    if sid not in _sandbox_sessions:
        return {"error": "unknown session"}, 404
    s = _sandbox_sessions[sid]
    path = s["summary"].get("jsonl") if fmt == "jsonl" else s["summary"].get("csv")
    if not path or not os.path.exists(path):
        return {"error": "file not ready"}, 404
    return send_file(path, as_attachment=True, download_name=f"sandbox_{sid}.{fmt}")

@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "enable_trading": os.getenv("ENABLE_TRADING", "false").lower() == "true",
        "paper_mode": os.getenv("PAPER_MODE", "true").lower() == "true",
    }, 200

@app.get("/sanity/schwab")
@login_required
def sanity_schwab():
    try:
        uid = getattr(current_user, "id", "demo-user")
        c = SchwabClient(uid)
        ph = c.price_history("SPY", period="1D", interval="1d")
        return {
            "ok": bool(ph.get("candles")),
            "uid": uid,
            "candles": len(ph.get("candles", [])),
        }, 200
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.get("/sanity/sandbox")
@login_required
def sanity_sandbox():
    return {
        "ok": True,
        "start": "/api/sandbox/start",
        "status": "/api/sandbox/status?session_id=<ID>",
        "download": "/api/sandbox/download?session_id=<ID>&fmt=jsonl|csv"
    }, 200

# --- PREVIEW: accepts single or vertical ---
# Unified preview endpoint (replace BOTH old copies with this one)
@app.post("/api/paper/options/preview", endpoint="api_paper_options_preview")
@login_required
def api_paper_options_preview():
    """
    Preview an options order (single or multi-leg).

    Accepts either:
      A) Simple single-leg shape:
         {
           "symbol": "AAPL", "side": "CALL"|"PUT",
           "strike": 190, "expiration": "2025-10-18",
           "price": 1.23, "quantity": 1,
           "orderType": "LIMIT", "duration": "DAY"
         }

      B) Normalized multi-leg shape:
         {
           "symbol": "AAPL", "quantity": 1,
           "orderType": "LIMIT", "duration": "DAY", "price": 1.23,
           "legs": [
             {"action":"BUY","side":"CALL","strike":190,"expiration":"2025-10-18","price":1.23},
             {"action":"SELL","side":"CALL","strike":195,"expiration":"2025-10-18","price":0.70}
           ]
         }
    """
    data = request.get_json(force=True) or {}

    # ---- Normalize to legs[] ----
    legs = data.get("legs")
    if not legs:
        # Single-leg → expand to legs[]
        try:
            legs = [{
                "action": data.get("action", "BUY"),
                "side":   str(data["side"]).upper(),                 # CALL/PUT (required)
                "strike": float(data["strike"]),                     # required
                "expiration": str(data["expiration"]),               # required (YYYY-MM-DD)
                "price": float(data.get("price") or 0.0)             # optional on preview
            }]
        except KeyError as e:
            return {"ok": False, "error": f"missing field: {e.args[0]}"}, 400
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid strike/price format"}, 400

    # Quantity / basic fields
    try:
        qty = int(data.get("quantity") or data.get("qty") or 1)
    except ValueError:
        return {"ok": False, "error": "quantity must be integer"}, 400

    symbol    = (data.get("symbol") or "AAPL").upper()
    orderType = (data.get("orderType") or "LIMIT").upper()
    duration  = (data.get("duration")  or "DAY").upper()
    limit_px  = data.get("price")

    # ---- Optional: compute spread stats if it's a 2-leg vertical ----
    try:
        stats = _spread_stats(legs)
    except Exception:
        stats = None

    # ---- Simple AI decision stub (keep your old behavior) ----
    # If you want the older BUY/SELL preview based on side, infer from first leg:
    first_side = str(legs[0].get("side", "CALL")).upper()
    # Old minimal preview style:
    # decision_min = {"signal": "BUY" if first_side == "CALL" else "SELL", "confidence": 93.4}
    # More descriptive combined style:
    decision = {
        "signal": "ENTER",
        "direction": ("LONG_CALL" if first_side == "CALL" else "LONG_PUT"),
        "confidence": 93.4,
        "notes": ["Preview with guardrails"]
    }

    payload = {
        "symbol": symbol,
        "quantity": qty,
        "legs": legs,
        "orderType": orderType,
        "duration": duration,
        "limitPrice": limit_px,
        "spread": stats
    }

    # ---- Audit (best-effort) ----
    try:
        audit_write("paper.preview", {"symbol": symbol, "payload": payload, "ai": decision})
    except Exception:
        pass

    return {"status": "ok", "order": payload, "ai": decision}

# ---- Normalized order -> Schwab order mapping (very small subset) ----
# ---- Instrument builders (equity / option) ----
def _equity_instr(symbol: str) -> dict:
    return {"assetType": "EQUITY", "symbol": symbol}

def _option_instr(symbol: str, expiration: str, side: str, strike: float) -> dict:
    # Basic TD/Schwab symbology for option legs (YYMMDD + C/P + strike*1000 style)
    return {
        "assetType": "OPTION",
        "symbol": f"{symbol}_{expiration.replace('-','')}{'C' if side.upper()=='CALL' else 'P'}{str(strike).replace('.','')}"
    }

def _leg_dict(o: dict, l: dict) -> dict:
    if l.get("asset","OPTION").upper() == "STOCK":
        return {
            "instrument": _equity_instr(o["symbol"]),
            "instruction": "Buy" if l["action"].upper()=="BUY" else "Sell",
            "quantity": int(l.get("quantity", 1)),
        }
    return {
        "instrument": _option_instr(o["symbol"], l["expiration"], l["side"], float(l["strike"])),
        "instruction": "Buy to Open" if l["action"].upper()=="BUY" else "Sell to Open",
        "quantity": int(l.get("quantity", 1)),
    }

# ---- Leaf (no children) order builder ----
def _leaf_single(o: dict, orderType: str, *, price=None, stopPrice=None, trail=None) -> dict:
    # SINGLE for one leg; MULTILEG for multiple (e.g., spreads, covered calls)
    strat = "MULTILEG" if len(o.get("legs",[])) > 1 else "SINGLE"
    out = {
        "orderStrategyType": strat,
        "orderType": orderType,                             # MARKET | LIMIT | STOP | STOP_LIMIT | TRAILING_STOP
        "session": o.get("session","NORMAL").upper(),       # NORMAL | AM | PM
        "duration": "DAY" if o.get("duration","DAY").upper()=="DAY" else "GOOD_TILL_CANCEL",
        "orderLegCollection": [_leg_dict(o, l) for l in o["legs"]],
    }
    if orderType == "LIMIT" and price is not None:
        out["price"] = f"{float(price):.2f}"
    if orderType in ("STOP", "STOP_LIMIT") and stopPrice is not None:
        out["stopPrice"] = f"{float(stopPrice):.2f}"
    if orderType == "STOP_LIMIT" and price is not None:
        out["price"] = f"{float(price):.2f}"
    if orderType == "TRAILING_STOP" and trail:
        # VALUE = $ offset, PERCENT = % offset; basis LAST/BID/ASK
        out["stopPriceLinkBasis"] = (trail.get("basis") or "LAST").upper()
        out["stopPriceLinkType"]  = (trail.get("type") or "VALUE").upper()      # VALUE | PERCENT
        out["stopPriceOffset"]    = float(trail.get("value") or 0)
        # Optional: out["activationPrice"] = ...
    return out

# ---- Composites: OCO & Trigger (OTO / OTOCO) ----
def _oco(children: list[dict]) -> dict:
    return {"orderStrategyType": "OCO", "childOrderStrategies": children}

def _trigger(parent: dict, children: list[dict]) -> dict:
    # One-Triggers-Others
    parent = dict(parent)
    parent["orderStrategyType"] = "TRIGGER"
    parent["childOrderStrategies"] = children
    return parent

# ---- Public mapper: normalized -> Schwab spec ----
def map_to_schwab_order(o: dict) -> dict:
    """
    Normalized payload -> Schwab order spec, including advanced structures.

    Expected normalized shape (superset):
    {
      account_id, symbol, strategy, orderType, duration, session?, price?, stopPrice?,
      trail?: { type: "VALUE"|"PERCENT", value: number, basis: "LAST"|"BID"|"ASK" },
      attached?: { target?: number, stop?: number, stopLimit?: number },
      locPrice?: number,              # for LOC fallback
      legs: [{ action, asset, side?, strike?, expiration?, quantity }]
    }
    """
    t = (o.get("orderType") or "LIMIT").upper()

    # Simple leaves
    if t in ("MARKET","LIMIT","STOP","STOP_LIMIT","TRAILING_STOP"):
        return _leaf_single(
            o, orderType=t,
            price=o.get("price"),
            stopPrice=o.get("stopPrice"),
            trail=o.get("trail"),
        )

    # OCO: two sibling exits (e.g., profit limit + protective stop/stop-limit)
    if t == "OCO":
        att = o.get("attached",{}) or {}
        tgt = _leaf_single({**o, "legs": o["legs"]}, "LIMIT", price=att.get("target"))
        if att.get("stopLimit") is not None:
            stp = _leaf_single({**o, "legs": o["legs"]}, "STOP_LIMIT",
                               price=att["stopLimit"], stopPrice=att.get("stop"))
        else:
            stp = _leaf_single({**o, "legs": o["legs"]}, "STOP", stopPrice=att.get("stop"))
        return _oco([tgt, stp])

    # BRACKET (OTOCO): entry (market/limit) that TRIGGERS an OCO (target + stop/stop-limit)
    if t == "BRACKET":
        entry = _leaf_single(o, "LIMIT" if o.get("price") else "MARKET", price=o.get("price"))
        oco   = map_to_schwab_order({**o, "orderType":"OCO"})
        return _trigger(entry, [oco])

    # FIRST_TRIGGERS (OTO): entry triggers a single child (target OR stop)
    if t == "FIRST_TRIGGERS":
        entry = _leaf_single(o, "LIMIT" if o.get("price") else "MARKET", price=o.get("price"))
        att = o.get("attached",{}) or {}
        if att.get("target") is not None:
            child = _leaf_single({**o, "legs": o["legs"]}, "LIMIT", price=att["target"])
        elif att.get("stopLimit") is not None:
            child = _leaf_single({**o, "legs": o["legs"]}, "STOP_LIMIT",
                                 price=att["stopLimit"], stopPrice=att.get("stop"))
        else:
            child = _leaf_single({**o, "legs": o["legs"]}, "STOP", stopPrice=att.get("stop"))
        return _trigger(entry, [child])

    # MOC / LOC: many public endpoints don’t accept literal flags -> server-schedule near close
    if t in ("MOC","LOC"):
        return {"_serverScheduled": True, "type": t, "locPrice": o.get("locPrice"), "normalized": o}

    # Fallback (safe)
    return _leaf_single(o, "LIMIT", price=o.get("price"))

# ---- Preview: compute risk & echo Schwab mapping (no live trading here) ----
@app.post("/api/trade/preview")
@login_required
def api_trade_preview():
    o = request.get_json(force=True)
    # your existing max P/L helper; supports SINGLE, VERTICAL, IRON_CONDOR, COVERED_CALL
    risk = compute_risk(o)
    sw = map_to_schwab_order(o)
    return {"ok": True, "risk": risk, "schwabOrder": sw}

# ---- Submit: honor ENABLE_TRADING/PAPER_MODE; schedule MOC/LOC; paper -> simulate/audit; live -> Schwab ----

@app.post("/api/trade/submit")
@login_required
def api_trade_submit():
    """
    Submit a trade (paper or live).
    Expects JSON with keys like:
      {
        "symbol": "AAPL",
        "account_id": "XXXXXXXX",
        "asset": "OPTION"|"STOCK",
        "side": "BUY"|"SELL",
        "right": "CALL"|"PUT",            # required for options
        "strike": 200,                    # required for options
        "expiry": "2025-10-18",           # YYYY-MM-DD, required for options
        "price": 1.25,                    # optional limit for paper fill & preview
        "_serverScheduled": false         # true for MOC/LOC scheduling path
      }
    Notes:
      - If ENABLE_TRADING=false, all submissions are blocked (even paper), but a preview is returned.
      - Paper mode is read from PAPER_MODE env (server-wide default); route does not override.
    """
    try:
        # ---- Inputs & flags
        o = request.get_json(force=True) or {}
        uid = getattr(current_user, "id", "user")

        enable = os.getenv("ENABLE_TRADING", "false").lower() == "true"
        paper  = os.getenv("PAPER_MODE", "true").lower() == "true"

        # Always map to Schwab order (for preview/audit), even if we'll block later.
        try:
            sw = map_to_schwab_order(o)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Order mapping failed: {e}"}), 400

        # ---- Global trading disable guard (keeps preview visible)
        if not enable:
            return jsonify({
                "ok": False,
                "error": "Trading disabled on server (ENABLE_TRADING=false).",
                "preview": sw
            }), 403

        # ---- MOC/LOC server-scheduled path
        if sw.get("_serverScheduled"):
            if not o.get("account_id"):
                return jsonify({"ok": False, "error": "Account ID required for MOC/LOC scheduling."}), 400
            info = _schedule_close_submit(uid, o["account_id"], o, paper_mode=paper)
            try:
                audit_write("order.close.scheduled", {
                    "user": uid,
                    "account": o["account_id"],
                    "normalized": o,
                    "schedule": info,
                    "mode": "paper" if paper else "live"
                })
            except Exception:
                pass
            return jsonify({"ok": True, "scheduled": info, "mode": "paper" if paper else "live"})

        # ---- PAPER path (non-close orders): simulate fill & audit, no external call
        if paper:
            fill_price = float(o.get("price") or 0.0)
            rec = {
                "ts": time.time(),
                "mode": "paper",
                "symbol": o.get("symbol"),
                "account": o.get("account_id"),
                "order": o,
                "schwab": sw,
                "fill_price": fill_price,
                "status": "FILLED"
            }
            try:
                audit_write("order.paper.fill", rec)
            except Exception:
                pass
            return jsonify({"ok": True, "paperFill": rec})

        # ---- LIVE path (non-close orders): immediate submit to Schwab
        try:
            if not o.get("account_id"):
                return jsonify({"ok": False, "error": "account_id required for live trading"}), 400

            c = SchwabClient(uid)
            account_id = o["account_id"]
            resp = c.place_order(account_id, sw)

            try:
                audit_write("order.live.submitted", {
                    "account": account_id, "order": o, "schwab": sw, "resp": resp
                })
            except Exception:
                pass

            return jsonify({"ok": True, "response": resp})
        except Exception as e:
            try:
                audit_write("order.live.error", {"order": o, "error": str(e)})
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500

    except Exception as e:
        # Top-level safety net
        return jsonify({"ok": False, "error": f"unexpected: {str(e)}"}), 500

# --- CHECKLIST → AUDIT ---
@app.post("/api/paper/options/checklist_audit")
@login_required
def api_paper_checklist_audit():
    payload = request.get_json(force=True)  # {symbol, plan, checks:{...}, legs?, qty?, spot?}
    try:
        audit_write("paper.checklist", payload)
    except Exception:
        pass
    return {"status":"ok"}






# --- V16: apply security headers globally ---
@app.after_request
def _sec_headers(resp):
    try:
        return security.add_security_headers(resp)
    except Exception:
        return resp

# --- V16: set CSRF cookie on GET HTML responses ---
@app.after_request
def _ensure_csrf(resp):
    try:
        if request.method == "GET" and resp.mimetype == "text/html":
            resp = security.set_csrf_cookie(resp)
    except Exception:
        pass
    return resp

# --- V16: protect admin routes if present ---
try:
    if 'admin_education' in globals():
        app.view_functions['admin_education'] = security.rate_limit('admin', capacity=20, refill_per_min=20)(
            security.csrf_protect(app.view_functions['admin_education']))
    if 'admin_podcast' in globals():
        app.view_functions['admin_podcast'] = security.rate_limit('admin', capacity=20, refill_per_min=20)(
            security.csrf_protect(app.view_functions['admin_podcast']))
except Exception:
    pass

# --- V16: protect trade endpoints if present ---
try:
    if 'api_trade_validate' in globals():
        app.view_functions['api_trade_validate'] = security.rate_limit('trade', capacity=30, refill_per_min=30)(
            app.view_functions['api_trade_validate'])
    if 'api_trade_preview' in globals():
        app.view_functions['api_trade_preview'] = security.rate_limit('trade', capacity=30, refill_per_min=30)(
            security.restrict_trading_to_allowed_users(app.view_functions['api_trade_preview']))
    if 'api_trade_submit' in globals():
        app.view_functions['api_trade_submit'] = security.rate_limit('trade', capacity=30, refill_per_min=30)(
            security.restrict_trading_to_allowed_users(app.view_functions['api_trade_submit']))
except Exception:
    pass
# --- security shim (no-op) ---
# ... all your routes above ...

# --- security shim (safe no-op if you don't have a real module) ---
try:
    security
except NameError:
    class _SecurityShim:
        def rate_limit(self, *args, **kwargs):
            def _wrap(f): return f
            return _wrap
        def csrf_protect(self, f): return f
        def restrict_trading_to_allowed_users(self, f): return f
        def add_security_headers(self, resp): return resp
        def set_csrf_cookie(self, resp): return resp
    security = _SecurityShim()

# --- Protect admin routes if present ---
try:
    if 'page_admin_education' in app.view_functions:
        app.view_functions['page_admin_education'] = security.rate_limit('admin', capacity=20, refill_per_min=20)(
            security.csrf_protect(app.view_functions['page_admin_education']))
    if 'page_admin_podcast' in app.view_functions:
        app.view_functions['page_admin_podcast'] = security.rate_limit('admin', capacity=20, refill_per_min=20)(
            security.csrf_protect(app.view_functions['page_admin_podcast']))
    if 'page_admin_bot' in app.view_functions:
        app.view_functions['page_admin_bot'] = security.rate_limit('admin', capacity=20, refill_per_min=20)(
            security.csrf_protect(app.view_functions['page_admin_bot']))
except Exception:
    pass

# --- Protect trade endpoints if present ---
try:
    if 'api_trade_preview' in app.view_functions:
        app.view_functions['api_trade_preview'] = security.rate_limit('trade', capacity=30, refill_per_min=30)(
            security.restrict_trading_to_allowed_users(app.view_functions['api_trade_preview']))
    if 'api_trade_submit' in app.view_functions:
        app.view_functions['api_trade_submit'] = security.rate_limit('trade', capacity=30, refill_per_min=30)(
            security.restrict_trading_to_allowed_users(app.view_functions['api_trade_submit']))
except Exception:
    pass

# optional: after_request hooks can stay below/above, both work
@app.after_request
def _sec_headers(resp):
    try: return security.add_security_headers(resp)
    except Exception: return resp

@app.after_request
def _ensure_csrf(resp):
    try:
        if request.method == "GET" and resp.mimetype == "text/html":
            resp = security.set_csrf_cookie(resp)
    except Exception:
        pass
    return resp

if __name__ == "__main__":
    app.run(debug=True)



