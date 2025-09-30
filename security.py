# V16: Security helpers (RBAC, CSRF, Rate Limit, Token Encryption, Headers)
import os, time, hmac, hashlib, base64, secrets, threading
from functools import wraps
from flask import request, abort, jsonify, make_response, g
try:
    from flask_login import current_user
except Exception:
    current_user = None

FERNET_KEY = os.environ.get("FERNET_KEY", "")
ALLOWED_TRADER_IDS = set([s.strip() for s in os.environ.get("ALLOWED_TRADER_IDS","").split(",") if s.strip()])
RATE_LIMIT_TRADE = int(os.environ.get("RATE_LIMIT_TRADE", "30"))
RATE_LIMIT_SCHWAB = int(os.environ.get("RATE_LIMIT_SCHWAB", "60"))
RATE_LIMIT_ADMIN = int(os.environ.get("RATE_LIMIT_ADMIN", "20"))

class _Bucket:
    __slots__ = ("tokens","updated")
    def __init__(self, tokens:int, updated:float):
        self.tokens = tokens; self.updated = updated

_BUCKETS = {}
_LOCK = threading.Lock()

def rate_limit(key:str, capacity:int, refill_per_min:int):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "0.0.0.0"
            k = f"{key}:{ip}"
            now = time.time()
            with _LOCK:
                b = _BUCKETS.get(k)
                if not b:
                    b = _Bucket(capacity, now); _BUCKETS[k] = b
                elapsed = now - b.updated
                refill = elapsed * (refill_per_min/60.0)
                if refill > 0:
                    b.tokens = min(capacity, b.tokens + refill)
                    b.updated = now
                if b.tokens < 1.0:
                    retry = int(max(1, 60 - (elapsed % 60)))
                    return jsonify({"ok": False, "error": {"code":"rate_limited","message":"Too many requests","retryAfter": retry}}), 429
                b.tokens -= 1.0
            return fn(*args, **kwargs)
        return wrapper
    return deco

def requires_role(*roles):
    roles = set(r.lower() for r in roles)
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = str(getattr(current_user, "id", "")).lower() if current_user else ""
            urole = str(getattr(current_user, "role", "")).lower()
            if roles and urole not in roles:
                return jsonify({"ok": False, "error": {"code":"forbidden","message":"Insufficient role"}}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco

def restrict_trading_to_allowed_users(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not ALLOWED_TRADER_IDS:
            uid = str(getattr(current_user, "id", "")).strip()
            if not uid:
                return jsonify({"ok": False, "error": {"code":"not_authorized","message":"Trading disabled for anonymous"}}), 403
            return fn(*args, **kwargs)
        else:
            uid = str(getattr(current_user, "id", "") or getattr(current_user, "email", "")).strip()
            if uid not in ALLOWED_TRADER_IDS:
                return jsonify({"ok": False, "error": {"code":"not_authorized","message":"Trading not permitted for this user in Individual mode"}}), 403
            return fn(*args, **kwargs)
    return wrapper

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

def _hmac(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

def set_csrf_cookie(resp):
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        secret = os.environ.get("CSRF_SECRET", "") or base64.urlsafe_b64encode(os.urandom(32)).decode()
        ts = str(int(time.time()) // 86400)
        token = _hmac(secret, ts) + "." + ts
        resp.set_cookie(CSRF_COOKIE, token, samesite="Lax", secure=True, httponly=False, max_age=86400)
    return resp

def csrf_protect(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method in ("POST","PUT","PATCH","DELETE"):
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not header or cookie.split(".",1)[0] != header:
                return jsonify({"ok": False, "error": {"code":"csrf","message":"CSRF token missing/invalid"}}), 403
        return fn(*args, **kwargs)
    return wrapper

def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    if not FERNET_KEY:
        return None
    try:
        return Fernet(FERNET_KEY.encode())
    except Exception:
        return None

def encrypt_token(plain: str) -> str:
    f = _get_fernet()
    if not f:
        return "b64:" + base64.urlsafe_b64encode(plain.encode()).decode()
    return "enc:" + f.encrypt(plain.encode()).decode()

def decrypt_token(token: str) -> str:
    if token.startswith("enc:"):
        f = _get_fernet()
        t = token[4:]
        if f:
            return f.decrypt(t.encode()).decode()
        raise ValueError("Missing FERNET_KEY for encrypted token")
    if token.startswith("b64:"):
        return base64.urlsafe_b64decode(token[4:].encode()).decode()
    return token

def add_security_headers(resp):
    resp.headers.setdefault("X-Frame-Options","DENY")
    resp.headers.setdefault("X-Content-Type-Options","nosniff")
    resp.headers.setdefault("Referrer-Policy","no-referrer")
    resp.headers.setdefault("Content-Security-Policy","default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'")
    return resp
