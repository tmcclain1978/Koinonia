try:
    from utils.settings_store import get_caps, set_caps
except Exception:
    get_caps = None; set_caps = None

try:
    from engine.execution_hooks import place_order_v2
except Exception:
    place_order_v2 = None

try:
    from engine.order_router import OrderRouter, RiskLimits, Mode
    from utils.config import cfg
    _ORDER_ROUTER = OrderRouter(mode=(Mode.DEMO if cfg.paper_mode else Mode.LIVE),
                                risk=RiskLimits(max_orders_per_hour=cfg.risk.max_orders_per_hour,
                                                max_daily_loss=cfg.risk.max_daily_loss,
                                                max_position=cfg.risk.max_position))
except Exception:
    _ORDER_ROUTER = None

try:
    from utils.logger_json import configure_json_logger
    configure_json_logger()
except Exception:
    pass

# ---- server.py (clean top-of-file header: paste this) ----
from __future__ import annotations

import os, sys, io, json, math, time, uuid, csv, threading, asyncio, secrets, pathlib, shutil
from datetime import datetime, timedelta
from collections import deque
from urllib.parse import urlencode

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    jsonify, Response, send_file, current_app
)
from flask_login import (
    LoginManager, login_user, login_required, logout_user, UserMixin, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
import requests
from pathlib import Path

# create ONE Flask app with correct template dir
app = Flask(__name__, template_folder=str(LEGACY_TEMPLATES), static_folder=None)

load_dotenv()

# --- BEGIN Advisor SPA + Legacy static mount ---
from pathlib import Path
from flask import send_from_directory, render_template
import os

BASE_DIR = Path(__file__).resolve().parent
LEGACY_TEMPLATES = BASE_DIR / "Legacy_flask" / "templates"
LEGACY_STATIC    = BASE_DIR / "Legacy_flask" / "static"
FRONTEND_BUILD   = BASE_DIR / "frontend" / "dist"  # Vite output

# Legacy static (old dashboard assets under /dashboard/static/...)
@app.route("/dashboard/static/<path:filename>", endpoint="dashboard_static")
def dashboard_static(filename):
    return send_from_directory(LEGACY_STATIC, filename)

# Dashboard (keep public while wiring; add @login_required later if desired)
@app.route("/dashboard", endpoint="dashboard")
def dashboard():
    return render_template("dashboard.html", admin_token=os.getenv("ADMIN_API_TOKEN",""))

# React Advisor SPA (Vite build)
@app.route("/dashboard/advisor", endpoint="page_advisor")
def advisor_index():
    return send_from_directory(FRONTEND_BUILD, "index.html")

@app.route("/dashboard/advisor/<path:path>", endpoint="advisor_assets")
def advisor_catchall(path):
    full = FRONTEND_BUILD / path
    if full.exists() and full.is_file():
        return send_from_directory(FRONTEND_BUILD, path)
    return send_from_directory(FRONTEND_BUILD, "index.html")
# --- END Advisor SPA + Legacy static mount ---

# If Vite:
FRONTEND_BUILD = BASE_DIR / "frontend" / "dist"
# If CRA (Create React App), use "build":
# FRONTEND_BUILD = BASE_DIR / "frontend" / "build"

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

login_manager = LoginManager()
login_manager.init_app(app)

@app.context_processor
def inject_runtime_flags():
    return {
        "ENABLE_TRADING": os.getenv("ENABLE_TRADING","false").lower() == "true",
        "PAPER_MODE": os.getenv("PAPER_MODE","true").lower() == "true",
    }

@app.route("/dev/login")
def dev_login():
    # guard to avoid enabling this in prod
    if os.getenv("FLASK_ENV","dev").lower() not in ("dev","development"):
        return {"error": "dev login disabled"}, 403

    u = User.query.filter_by(email="demo@example.com").first()
    if not u:
        u = User(
            username="demo",
            email="demo@example.com",
            password_hash=generate_password_hash("Passw0rd!"),
            created_at=datetime.utcnow()
        )
        db.session.add(u); db.session.commit()

    login_user(u, remember=True)
    return redirect(url_for("dashboard"))
# ---------------- Globals/Paths ----------------
AUDIT_PATH = os.getenv("TRADE_AUDIT_PATH", os.path.join("data", "trade_audit.jsonl"))

# ---------------- AI engine singleton ----------------
from ai.engine import AIEngine   # import the class, not the package
AI = AIEngine(os.getenv("AI_MODEL_PATH"))

# ---------------- Blueprints (import AFTER app is created) ----------------
from candle_routes import candle_routes
from integrations.schwab_adapter import api as schwab_bp, SchwabClient, fetch_features
from ai.sandbox import sandbox_bp

app.register_blueprint(schwab_bp)
app.register_blueprint(candle_routes)
app.register_blueprint(sandbox_bp)

# ---------------- Scheduler (for MOC/LOC helper) ----------------
from pytz import timezone
_sched = BackgroundScheduler()
_sched.start()
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
from flask import send_from_directory
from pathlib import Path


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

class SchwabCredential(db.Model):
    __tablename__ = "schwab_credentials"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True, nullable=False, unique=True)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.Integer, nullable=False)
    scope = db.Column(db.String(255))

with app.app_context():
  

# -----------------------------
# Options AI Bot (repurposed from PocketOptions)
# -----------------------------
class OptionsAIBot:
    def __init__(self, symbols, strategy_config: StrategyConfig = None):
        self.symbols = symbols
        self.strategy_config = strategy_config or StrategyConfig()
        from ai.options_ai_bot import OptionsAIBot
        self.engine = OptionsAIBot(user_id=getattr(current_user, "id", "user"))


    def evaluate_signals(self):
        suggestions = []
        for sym in self.symbols:
            try:
                # Placeholder: load last candles (future: hook Schwab option chain & greeks)
                candles = get_candles_with_fallback(sym, "1m", limit=50)
                if not candles:
                    continue
                signal, conf, reason = self.engine.evaluate(candles)
                suggestions.append({
                    "symbol": sym,
                    "side": signal,
                    "confidence": conf,
                    "reason": reason
                })
            except Exception as e:
                continue
        return suggestions

options_ai_bot = OptionsAIBot(["AAPL", "MSFT", "NVDA", "SPY"])

@app.route("/api/ai/options_signals")
@login_required
def api_ai_options_signals():
    sugg = options_ai_bot.evaluate_signals()
    # Persist to DB
    conn = sqlite3.connect("signals.db"); cur = conn.cursor()
    for s in sugg:
        cur.execute("INSERT INTO ai_signals(user_id, symbol, side, confidence, reason, created_at) VALUES(?,?,?,?,?,datetime('now'))",
                    (current_user.id, s["symbol"], s["side"], s["confidence"], s["reason"]))
    conn.commit(); conn.close()
    caps = get_caps() if get_caps else None
                    return jsonify({"signals": sugg})

@app.post("/api/ai/propose")
@login_required
def ai_propose():
    data   = request.get_json(force=True)
    symbol = data.get("symbol", "AAPL")
    uid    = session.get("user_id")  # or however you store user id

    feats = fetch_features(uid, symbol,
                           period=data.get("period", "1D"),
                           interval=data.get("interval", "1m"))
    # decision = ai_engine.propose(symbol=symbol, features=feats, risk=data.get("risk"))
    decision = {"symbol": symbol, "side": "BUY", "qty": 1, "confidence": 0.62, "features": feats}
    return jsonify(decision)

LEGACY_STATIC = BASE_DIR / "Legacy_flask" / "static"

# -----------------------------
# Existing endpoints (expected move, bracket, scanner, journal, etc.) remain below...
# -----------------------------


# -----------------------------
# AI Options Bot (adapts AIEngine signals → option suggestions)
# -----------------------------
# Configurable knobs (env or defaults)
OPT_DEFAULT_DTE = int(os.getenv("OPT_DEFAULT_DTE", 1))          # days to expiry target
OPT_TARGET_DELTA = float(os.getenv("OPT_TARGET_DELTA", 0.30))    # desired option delta
OPT_DEFAULT_QTY = int(os.getenv("OPT_DEFAULT_QTY", 1))
OPT_ENABLE_STAGE = os.getenv("OPT_ENABLE_STAGE", "false").lower() == "true"  # auto-stage (paper only)

class OptionsAIBot:
    """Maps PocketOptions signals to option trade ideas.
    If options chain/greeks are not available, uses heuristic moneyness bands.
    """
    def __init__(self, engine: PocketOptionsAIEngine, symbols: list[str]):
        self.engine = engine
        self.symbols = symbols

    def _signal_for(self, symbol: str):
        # Integrate your existing PocketOptions AI engine; fallback if unavailable
        try:
            sig = self.engine.predict_signal(symbol)
            # expected shape: {"side":"BUY"|"SELL", "confidence":float, ...}
            return sig
        except Exception:
            # fallback: reuse simple bot
            last = _quote_last(symbol)
            if last is None:
                return None
            side = "BUY" if int(time.time()) % 2 == 0 else "SELL"
            return {"side": side, "confidence": 0.55}

    def _select_contract(self, symbol: str, last: float, side: str, dte: int, target_delta: float):
        """Heuristic contract selection without full chain access.
        Approx map: delta≈0.3 ~ 3–5% OTM for 0–2 DTE large caps. We'll use 4%.
        """
        otm_pct = 0.04 if target_delta <= 0.35 else 0.02
        if side == "BUY":  # bullish → long CALL
            right = "CALL"
            strike = round(last * (1 + otm_pct), 2)
        else:               # bearish → long PUT
            right = "PUT"
            strike = round(last * (1 - otm_pct), 2)
        expiry_hint = f"+{dte}d"  # hint; replace with real nearest expiry when chain available
        return {"right": right, "strike": strike, "expiry_hint": expiry_hint, "target_delta": target_delta}

    def suggestions(self, dte: int | None = None, target_delta: float | None = None, qty: int | None = None):
        dte = dte or OPT_DEFAULT_DTE
        target_delta = target_delta or OPT_TARGET_DELTA
        qty = qty or OPT_DEFAULT_QTY
        out = []
        for sym in self.symbols:
            sig = self._signal_for(sym)
            if not sig:
                continue
            last = _quote_last(sym)
            if last is None:
                continue
            side = sig["side"].upper()
            conf = float(sig.get("confidence", 0.5))
            contract = self._select_contract(sym, last, side, dte, target_delta)
            out.append({
                "symbol": sym,
                "underlying_last": last,
                "direction": side,
                "confidence": round(conf, 3),
                "order": {"right": contract["right"], "strike": contract["strike"], "expiry": contract["expiry_hint"], "qty": qty},
                "selection": {"method": "heuristic", "target_delta": contract["target_delta"]}
            })
        return out

# Instantiate the options bot with your existing engine (if available)
try:
    _po_engine = PocketOptionsAIEngine(StrategyConfig())
except Exception:
    _po_engine = None

options_ai_bot = OptionsAIBot(_po_engine, ["AAPL","MSFT","NVDA","SPY"])  # start set

@app.route("/api/ai/options/signals")
@login_required
def api_ai_options_signals():
    dte = request.args.get("dte", type=int) or OPT_DEFAULT_DTE
    tdelta = request.args.get("delta", type=float) or OPT_TARGET_DELTA
    qty = request.args.get("qty", type=int) or OPT_DEFAULT_QTY
    ideas = options_ai_bot.suggestions(dte=dte, target_delta=tdelta, qty=qty)

    # Optionally auto-stage as journal entries (paper only)
    staged = []
    if OPT_ENABLE_STAGE and PAPER_MODE:
        conn = sqlite3.connect("signals.db"); cur = conn.cursor()
        for idea in ideas:
            ord = idea["order"]
            cur.execute(
                """
                INSERT INTO trade_journal(user_id, broker, account_id, symbol, right, strike, expiry, side, qty, entry_px, setup, checklist_json, notes, opened_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    current_user.id, "schwab", "", idea["symbol"], ord["right"], ord["strike"], ord["expiry"],
                    "BUY", ord["qty"], idea["underlying_last"], "AI_options_v1", json.dumps({"conf": idea["confidence"]}),
                    "staged by AI"
                )
            )
            staged.append({"symbol": idea["symbol"], "order": ord})
        conn.commit(); conn.close()

    caps = get_caps() if get_caps else None
                    return jsonify({"ideas": ideas, "staged": staged, "paper_mode": PAPER_MODE, "auto_stage": OPT_ENABLE_STAGE})

@app.route("/api/ai/options/config", methods=["POST"]) 
@login_required
def api_ai_options_config():
    body = request.get_json() or {}
    global OPT_DEFAULT_DTE, OPT_TARGET_DELTA, OPT_DEFAULT_QTY
    if "dte" in body: OPT_DEFAULT_DTE = int(body["dte"]) or OPT_DEFAULT_DTE
    if "delta" in body: OPT_TARGET_DELTA = float(body["delta"]) or OPT_TARGET_DELTA
    if "qty" in body: OPT_DEFAULT_QTY = int(body["qty"]) or OPT_DEFAULT_QTY
    caps = get_caps() if get_caps else None
                    return jsonify({"dte": OPT_DEFAULT_DTE, "delta": OPT_TARGET_DELTA, "qty": OPT_DEFAULT_QTY})

@app.context_processor
def inject_runtime_flags():
    return {
        "ENABLE_TRADING": os.getenv("ENABLE_TRADING", "false").lower() == "true",
        "PAPER_MODE": os.getenv("PAPER_MODE", "true").lower() == "true",
    }

# ---------- HTML routes ----------
@app.route("/advisor")
@login_required
def advisor():
    # If you're already using /dashboard as the main page, you can alias or
    # point this to a more advisor-centric template. For now we reuse dashboard.html:
    return render_template("dashboard.html", admin_token=os.getenv("ADMIN_API_TOKEN", ""))

@app.route("/audit")
@login_required
def audit():
    return render_template("audit.html")

 #--- Analytics page ---
@app.route("/options/analytics")
@login_required
def options_analytics():
    return render_template(
        "analytics_options.html",
        admin_token=os.getenv("ADMIN_API_TOKEN", "")
    )

# --- Paper trading (Route B: plural filename) ---
@app.route("/paper/options")
@login_required
def paper_options():
    return render_template(
        "paper_options.html",
        admin_token=os.getenv("ADMIN_API_TOKEN", "")
    )

@app.route("/trade/orders")
@login_required
def trade_orders():
    return render_template(
        "trade_orders.html",
        admin_token=os.getenv("ADMIN_API_TOKEN", "")
    )
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
        caps = get_caps() if get_caps else None
                    return jsonify({"ok": True, "message": "Refreshed (if needed).", "token": _read_token_meta(uid)})
    except Exception as e:
        caps = get_caps() if get_caps else None
                    return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/schwab/admin/delete")
@login_required
def schwab_admin_delete():
    uid = getattr(current_user, "id", "demo-user")
    path = _token_path(uid)
    try:
        if os.path.exists(path):
            os.remove(path)
        caps = get_caps() if get_caps else None
                    return jsonify({"ok": True, "message": f"Deleted token {path}"})
    except Exception as e:
        caps = get_caps() if get_caps else None
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
        caps = get_caps() if get_caps else None
                    return jsonify({"url": c.build_authorize_url()})
    except Exception as e:
        caps = get_caps() if get_caps else None
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

@app.post("/api/paper/options/preview")
@login_required
def api_paper_preview():
    order = request.get_json(force=True)
    # call your AI; here we synthesize:
    decision = {"signal": "BUY" if order["side"]=="CALL" else "SELL", "confidence": 93.4}
    return {"status":"ok","order":order,"ai":decision}

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
@app.post("/api/paper/options/preview")
@login_required
def api_paper_preview():
    data = request.get_json(force=True)
    # normalize schema
    if "legs" not in data:
        # single-leg -> expand to legs[]
        data["legs"] = [{
            "action": "BUY",
            "side": data["side"],           # CALL/PUT
            "strike": float(data["strike"]),
            "expiration": data["expiration"],
            "price": float(data.get("price") or 0.0)  # optional on preview
        }]
    qty = int(data.get("quantity", 1))

    # compute spread stats if vertical
    stats = _spread_stats(data["legs"])

    # synthesize AI call or hook your real engine here
    decision = {"signal": "ENTER", "confidence": 93.4, "notes": ["Preview with guardrails"]}

    payload = {
        "symbol": data["symbol"],
        "quantity": qty,
        "legs": data["legs"],
        "orderType": data.get("orderType","LIMIT"),
        "duration": data.get("duration","DAY"),
        "limitPrice": data.get("price"),           # optional here
        "spread": stats
    }
    # (optional) write preview into audit
    try:
        audit_write("paper.preview", {"symbol": data["symbol"], "payload": payload, "ai": decision})
    except Exception:
        pass
    return {"status":"ok","order":payload,"ai":decision}
# --- SIMULATE: compute P/L at expiration around spot±range ---
@app.post("/api/paper/options/simulate")
@login_required
def api_paper_sim():
    global _paper_eq
    data = request.get_json(force=True)
    legs = data.get("legs")
    if not legs:
        # single -> expand
        legs = [{
            "action": "BUY",
            "side": data["side"],
            "strike": float(data["strike"]),
            "expiration": data["expiration"],
            "price": float(data.get("price") or 0.0)
        }]
    qty = int(data.get("quantity", 1))
    symbol = data["symbol"]

    # pick a hypothetical expiration spot using a mild random % move
    import random
    base = float(request.args.get("spot", "0") or 0.0)
    if base <= 0:
        # no spot passed in; simulate around 100
        base = 100.0
    move = random.uniform(-0.05, 0.05)  # ±5% shock
    S_T = base * (1.0 + move)

    pl = _pl_expiration(symbol, legs, S_T, qty)
    _paper_eq += pl

    rec = {
        "ts": time.time(), "symbol": symbol, "qty": qty,
        "legs": legs, "S_T": round(S_T,2),
        "pl": round(pl,2), "mode": "sim"
    }
    _paper_log.append(rec)
    try:
        audit_write("paper.sim", rec)
    except Exception:
        pass
    return {"message":"Simulated", "record":rec}

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
    o = request.get_json(force=True)
    uid = getattr(current_user, "id", "user")
    enable = os.getenv("ENABLE_TRADING","false").lower()=="true"
    paper  = os.getenv("PAPER_MODE","true").lower()=="true"

    # Always map, even for paper, so you can inspect in the UI
    sw = map_to_schwab_order(o)

    # Trading globally disabled -> block (still return preview)
    if not enable:
        return {"ok": False, "error": "Trading disabled on server (ENABLE_TRADING=false).", "preview": sw}, 403

    # MOC/LOC path: schedule a near-close submission (paper: audit-only, live: place order)
    if sw.get("_serverScheduled"):
        if not o.get("account_id"):
            return {"ok": False, "error": "Account ID required for MOC/LOC scheduling."}, 400
        info = _schedule_close_submit(uid, o["account_id"], o, paper_mode=paper)
        try:
            audit_write("order.close.scheduled", {"user": uid, "account": o["account_id"], "normalized": o, "schedule": info, "mode": "paper" if paper else "live"})
        except Exception:
            pass
        return {"ok": True, "scheduled": info, "mode": "paper" if paper else "live"}

    # PAPER (non-close orders): record simulated fill, append to audit, no external call
    if paper:
        fill_price = float(o.get("price") or 0.0)
        rec = {
            "ts": time.time(), "mode": "paper", "symbol": o.get("symbol"), "account": o.get("account_id"),
            "order": o, "schwab": sw, "fill_price": fill_price, "status": "FILLED"
        }
        try:
            audit_write("order.paper.fill", rec)
        except Exception:
            pass
        return {"ok": True, "paperFill": rec}

    # LIVE (non-close orders): submit immediately to Schwab
    try:
        c = SchwabClient(uid)
        account_id = o["account_id"]
        resp = c.place_order(account_id, sw)
        audit_write("order.live.submitted", {"account": account_id, "order": o, "schwab": sw, "resp": resp})
        return {"ok": True, "response": resp}
    except Exception as e:
        audit_write("order.live.error", {"order": o, "error": str(e)})
        return {"ok": False, "error": str(e)}, 500

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





# --- Injected full health endpoint ---
try:
    from utils.healthcheck import run_full_healthcheck
    from flask import jsonify
    @app.route("/health/full", methods=["GET","POST"])
    def full_health():
        # TODO: wire real db session, scraper smoke, and forecast smoke
        res = run_full_healthcheck(db_session=None, scraper_fn=lambda: True, forecast_fn=lambda: True)
        return jsonify(res), (200 if res.get("status")=="ok" else 500)
except Exception as _e:
    pass


# --- Injected: Risk config read-only API ---
try:
    from flask import jsonify
    from utils.config import cfg as _cfg
    @app.route("/api/risk_config", methods=["GET","POST"])
    def api_risk_config():
        caps = get_caps() if get_caps else None
                    return jsonify({
            "max_orders_per_hour": _cfg.risk.max_orders_per_hour,
            "max_daily_loss": _cfg.risk.max_daily_loss,
            "max_position": _cfg.risk.max_position,
            "paper_mode": _cfg.paper_mode,
            "enable_trading": _cfg.enable_trading
        })
except Exception as _e:
    pass


# --- Injected: V2 unified order endpoint (demo/live) ---
try:
    from flask import request, jsonify
    @app.route("/api/v2/order", methods=["POST"])
    def api_order_v2():
        if place_order_v2 is None:
            caps = get_caps() if get_caps else None
                    return jsonify({"ok": False, "error": "router_unavailable"}), 503
        data = request.get_json(force=True) or {}
        mode = str(data.get("mode","demo"))
        side = str(data.get("side","call"))
        stake = float(data.get("stake", 1.0))
        symbol = str(data.get("symbol","EURUSD-OTC"))
        idk = data.get("idempotency_key")
        res = place_order_v2(mode=mode, side=side, stake=stake, symbol=symbol, idemp_key=idk)
        code = 200 if res.get("ok") else 429 if "circuit" in str(res.get("error","")) else 400
        return jsonify(res), code
except Exception as _e:
    pass


# --- Injected: Use health smokes in /health/full if present ---
try:
    from utils.health_smokes import db_ping as _db_ping, scraper_smoke as _scraper_smoke, forecast_smoke as _forecast_smoke
    @app.route("/health/full2", methods=["GET","POST"])
    def full_health2():
        try:
            db_ok = False
            try:
                # If you use SQLAlchemy, wire a Session here
                db_ok = False  # placeholder unless session available
            except Exception:
                db_ok = False
            res = {
                "db": db_ok,
                "scraper": _scraper_smoke(),
                "forecast": _forecast_smoke(),
            }
            res["status"] = "ok" if all(res.values()) else "fail"
            return jsonify(res), (200 if res["status"]=="ok" else 500)
        except Exception as e:
            caps = get_caps() if get_caps else None
                    return jsonify({"status":"fail","error":str(e)}), 500
except Exception as _e:
    pass


try:
    import json, os
    from utils.config import cfg as _cfg
    @app.route("/api/risk_config", methods=["POST"])
    def api_risk_config_update():
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        # Update in-memory (best-effort; real apps persist to DB)
        if "max_orders_per_hour" in data:
            _cfg.risk.max_orders_per_hour = int(data["max_orders_per_hour"])
        if "max_daily_loss" in data:
            _cfg.risk.max_daily_loss = float(data["max_daily_loss"])
        if "max_position" in data:
            _cfg.risk.max_position = float(data["max_position"])
        # Write to a lightweight json so restarts keep it (optional)
        os.makedirs("config", exist_ok=True)
        with open("config/risk.json","w",encoding="utf-8") as f:
            json.dump({
                "max_orders_per_hour": _cfg.risk.max_orders_per_hour,
                "max_daily_loss": _cfg.risk.max_daily_loss,
                "max_position": _cfg.risk.max_position
            }, f)
        caps = get_caps() if get_caps else None
                    return jsonify({"ok": True})
except Exception as _e:
    pass


# --- Injected: Risk Settings Page ---
try:
    from flask import render_template
    @app.route("/admin/risk", methods=["GET"])
    def view_risk_settings():
        return render_template("risk_settings.html")
except Exception as _e:
    pass


try:
    from utils.settings_store import RiskCaps as _RiskCaps
    # replace in-memory update with persistent store
    @app.after_request
    def _noop(r):
        return r
except Exception as _e:
    pass


# --- Injected: Robust risk_config v2 using settings_store ---
try:
    from flask import jsonify, request
    @app.route("/api/risk_config_v2", methods=["GET"])
    def api_risk_v2_get():
        if not get_caps:
            return jsonify({"ok": False, "error": "store_unavailable"}), 503
        c = get_caps()
        return jsonify({
            "ok": True,
            "max_orders_per_hour": c.max_orders_per_hour,
            "max_daily_loss": c.max_daily_loss,
            "max_position": c.max_position
        })

    @app.route("/api/risk_config_v2", methods=["POST"])
    def api_risk_v2_post():
        if not set_caps:
            return jsonify({"ok": False, "error": "store_unavailable"}), 503
        data = request.get_json(force=True) or {}
        c = get_caps()
        if "max_orders_per_hour" in data:
            c.max_orders_per_hour = int(data["max_orders_per_hour"])
        if "max_daily_loss" in data:
            c.max_daily_loss = float(data["max_daily_loss"])
        if "max_position" in data:
            c.max_position = float(data["max_position"])
        set_caps(c)
        return jsonify({"ok": True})
except Exception as _e:
    pass


# --- Injected: Education videos page ---
try:
    from flask import render_template
    @app.route("/education", methods=["GET"])
    def view_education():
        # Example data; replace with DB entries or CMS later
        videos = [
            {"title":"Options 101 — Calls & Puts","url":"/static/media/options101.mp4","duration":"12:34","category":"basics","poster":""},
            {"title":"Greeks Deep Dive — Delta, Gamma, Theta, Vega","url":"/static/media/greeks_deep_dive.mp4","duration":"18:22","category":"strategies","poster":""},
            {"title":"Risk & Position Sizing","url":"/static/media/risk_position_sizing.mp4","duration":"09:48","category":"risk","poster":""},
            {"title":"Platform Pro Tips — Faster Workflows","url":"/static/media/platform_pro_tips.mp4","duration":"07:50","category":"platform","poster":""},
        ]
        return render_template("education.html", year=2025, videos=videos, current_video=videos[0], current_category="basics")
except Exception as _e:
    pass


# --- Injected: You Got Options podcast page ---
try:
    from flask import render_template
    @app.route("/podcast", methods=["GET"])
    def view_podcast():
        episodes = [
            {"title":"Episode 01 — The Mindset of Risk","url":"/static/media/ep01_mindset.mp4","date":"2025-07-01","duration":"28:05"},
            {"title":"Episode 02 — Trend vs Mean Reversion","url":"/static/media/ep02_trend_vs_mr.mp4","date":"2025-08-10","duration":"31:44"},
            {"title":"Episode 03 — Edges in OTC","url":"/static/media/ep03_edges_otc.mp4","date":"2025-09-01","duration":"24:19"},
        ]
        live_url = ""  # Set to HLS URL when available, e.g., "https://example.com/live/you-got-options.m3u8"
        return render_template("podcast.html", episodes=episodes, live_url=live_url)
except Exception as _e:
    pass


# --- Injected: Chart data API (demo) ---
try:
    @app.get("/api/chart/data")
    @login_required
    def api_chart_data():
        import random, time
        # Synthetic OHLCV for demo; replace with real source (Schwab price_history or DB)
        now = int(time.time())
        bars = []
        o = 100.0
        for i in range(500):
            t = now - (500-i)*60
            h = o + random.uniform(0, 1.5)
            l = o - random.uniform(0, 1.5)
            c = l + (h-l)*random.random()
            v = random.randint(1000, 5000)
            bars.append({"t": t, "o": round(o,2), "h": round(h,2), "l": round(l,2), "c": round(c,2), "v": v})
            o = c
        return {"bars": bars}
except Exception as _e:
    pass


# --- Injected: Chart state persistence (file-based; DB-ready) ---
try:
    from flask import request, jsonify, Response
    import os, json
    _CS_DIR = os.path.join("data","chart_state")
    os.makedirs(_CS_DIR, exist_ok=True)

    def _cs_path(uid: str, symbol: str, interval: str) -> str:
        safe = f"{uid}_{symbol}_{interval}".replace("/","-")
        return os.path.join(_CS_DIR, safe + ".json")

    @app.get("/api/chart/state")
    @login_required
    def api_chart_state_get():
        uid = getattr(current_user, "id", "user")
        symbol = request.args.get("symbol","AAPL").upper()
        interval = request.args.get("interval","1m")
        path = _cs_path(uid, symbol, interval)
        if not os.path.exists(path):
            return {"ok": True, "drawings": [], "overlays": {}, "tool": "cursor"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"ok": True, **data}
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500

    @app.post("/api/chart/state")
    @login_required
    def api_chart_state_post():
        uid = getattr(current_user, "id", "user")
        data = request.get_json(force=True) or {}
        symbol = (data.get("symbol") or "AAPL").upper()
        interval = data.get("interval") or "1m"
        path = _cs_path(uid, symbol, interval)
        payload = {"drawings": data.get("drawings", []),
                   "overlays": data.get("overlays", {}),
                   "tool": data.get("tool", "cursor")}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500
except Exception as _e:
    pass


# --- Injected: SSE stream for ticks (synthetic fallback) ---
try:
    import time, random
    @app.get("/api/chart/stream")
    @login_required
    def api_chart_stream():
        symbol = request.args.get("symbol","AAPL").upper()
        def gen():
            last = 100.0
            while True:
                # In real impl, read from Schwab websocket bridge or DB tail
                delta = random.uniform(-0.2, 0.2)
                last = max(1.0, last + delta)
                yield f"data: {{\"symbol\": \"{symbol}\", \"last\": {last:.2f}, \"ts\": {int(time.time()*1000)} }}\n\n"
                time.sleep(1.0)
        return Response(gen(), mimetype="text/event-stream")
except Exception as _e:
    pass
