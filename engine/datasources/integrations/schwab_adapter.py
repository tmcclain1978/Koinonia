# integrations/schwab_adapter.py
from __future__ import annotations
import os, json, time, base64, hashlib, secrets, pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
import numpy as np
from flask import Blueprint, current_app, request, jsonify, redirect
from itsdangerous import URLSafeSerializer

# ========= Config helpers =========
def cfg(key: str, default: Optional[str] = None):
    return os.getenv(key, default)

SCHWAB_API_URL   = cfg("SCHWAB_API_URL", "https://api.schwabapi.com")
SCHWAB_AUTH_URL  = cfg("SCHWAB_AUTH_URL", "https://api.schwabapi.com/v1/oauth2/authorize")
SCHWAB_TOKEN_URL = cfg("SCHWAB_TOKEN_URL", "https://api.schwabapi.com/v1/oauth2/token")
SCHWAB_CLIENT_ID = cfg("SCHWAB_CLIENT_ID", "")
SCHWAB_REDIRECT  = cfg("SCHWAB_REDIRECT_URI", "http://localhost:8443/auth/callback")
TOKEN_DIR        = cfg("SCHWAB_TOKEN_PATH", ".tokens")
APP_SECRET       = cfg("APP_SECRET", secrets.token_hex(16))

pathlib.Path(TOKEN_DIR).mkdir(parents=True, exist_ok=True)

# ========= PKCE & state =========
class PKCE:
    @staticmethod
    def new_verifier() -> str:
        return base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip("=")
    @staticmethod
    def challenge(v: str) -> str:
        h = hashlib.sha256(v.encode()).digest()
        return base64.urlsafe_b64encode(h).decode().rstrip("=")

signer = URLSafeSerializer(APP_SECRET, salt="schwab-pkce-state")

def make_state(uid: str, verifier: str) -> str:
    return signer.dumps({"uid": uid, "cv": verifier, "ts": int(time.time())})

def read_state(state: str) -> Dict[str, Any]:
    return signer.loads(state)

# ========= Token store =========
@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: int

class TokenStore:
    def __init__(self, base_dir: str):
        self.base = pathlib.Path(base_dir)
    def path_for(self, uid: str) -> pathlib.Path:
        return self.base / f"{uid}.json"
    def load(self, uid: str) -> Optional[TokenBundle]:
        p = self.path_for(uid)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return TokenBundle(**data)
    def save(self, uid: str, tb: TokenBundle):
        self.path_for(uid).write_text(json.dumps(tb.__dict__, indent=2))
    def all_users(self) -> List[str]:
        return [p.stem for p in self.base.glob("*.json")]

TOKENS = TokenStore(TOKEN_DIR)
# ========= Schwab API client =========
class SchwabClient:
    def __init__(self, user_id: str):
        self.uid = user_id
        self.client_id = SCHWAB_CLIENT_ID
        self.redirect  = SCHWAB_REDIRECT
        self.auth      = SCHWAB_AUTH_URL
        self.token     = SCHWAB_TOKEN_URL
        self.api       = SCHWAB_API_URL

    # --- OAuth: build login URL with PKCE ---
    def login_url(self) -> Dict[str, str]:
        verifier  = PKCE.new_verifier()
        challenge = PKCE.challenge(verifier)
        state     = make_state(self.uid, verifier)
        # Persist verifier by embedding in signed state
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Ask only for scopes your app has been approved for
            "scope": "marketdata trading read write",
            "state": state,
        }
        return {"url": f"{self.auth}?{urlencode(params)}", "state": state}

    # --- OAuth: exchange authorization code for tokens ---
    def exchange_code(self, code: str, state: str) -> "TokenBundle":
        payload  = read_state(state)
        verifier = payload["cv"]
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        secret = os.getenv("SCHWAB_CLIENT_SECRET")
        if secret:
            data["client_secret"] = secret
 
        with httpx.Client(timeout=30) as s:
            r = s.post(self.token, data=data)
            r.raise_for_status()
            tok = r.json()
        tb = TokenBundle(
            access_token = tok["access_token"],
            refresh_token = tok.get("refresh_token", ""),
            expires_at = int(time.time()) + int(tok.get("expires_in", 1800)) - 60,
        )
        TOKENS.save(self.uid, tb)
        return tb

    # --- Token ensure/refresh ---
    def ensure_token(self) -> "TokenBundle":
        tb = TOKENS.load(self.uid)
        if not tb:
            raise RuntimeError("No Schwab token; call /api/schwab/auth/login first.")
        if time.time() < tb.expires_at:
            return tb
        data = {
            "grant_type": "refresh_token",
            "refresh_token": tb.refresh_token,
            "client_id": self.client_id,
        }
        secret = os.getenv("SCHWAB_CLIENT_SECRET")
        if secret:
            data["client_secret"] = secret

        with httpx.Client(timeout=30) as s:
            r = s.post(self.token, data=data)
            r.raise_for_status()
            tok = r.json()
        tb = TokenBundle(
            access_token = tok["access_token"],
            refresh_token = tok.get("refresh_token", tb.refresh_token),
            expires_at = int(time.time()) + int(tok.get("expires_in", 1800)) - 60,
        )
        TOKENS.save(self.uid, tb)
        return tb

    # --- Core request helper ---
    def _req(self, method: str, path: str, *, params=None, json_body=None) -> Any:
        tb = self.ensure_token()
        headers = {"Authorization": f"Bearer {tb.access_token}"}
        url = f"{self.api}{path}"
        with httpx.Client(timeout=30) as s:
            r = s.request(method, url, params=params, json=json_body, headers=headers)
            if r.status_code == 401:
                # one refresh retry
                tb = self.ensure_token()
                headers["Authorization"] = f"Bearer {tb.access_token}"
                r = s.request(method, url, params=params, json=json_body, headers=headers)
            r.raise_for_status()
            return r.json()

    # --- Market Data ---
    def quotes(self, symbols: List[str]) -> Any:
        return self._req("GET", "/marketdata/v1/quotes",
                         params={"symbols": ",".join(symbols)})

    def price_history(self, symbol: str, period: str = "1D", interval: str = "1m") -> Any:
        return self._req("GET", f"/marketdata/v1/pricehistory/{symbol}",
                         params={"period": period, "interval": interval})

    def option_chains(self, symbol: str, **kwargs) -> Any:
        params = {"symbol": symbol}
        params.update(kwargs)
        return self._req("GET", "/marketdata/v1/options/chains", params=params)

    # --- Accounts & Trading ---
    def accounts(self) -> Any:
        return self._req("GET", "/accounts/v1/accounts")

    def positions(self, account_id: str) -> Any:
        return self._req("GET", f"/accounts/v1/accounts/{account_id}/positions")

    def place_order(self, account_id: str, order: Dict[str, Any]) -> Any:
        return self._req("POST", f"/accounts/v1/accounts/{account_id}/orders",
                         json_body=order)
# ========= TA & Chain adapters =========
def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(arr).ewm(span=span, adjust=False).mean().values

def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(prices, prepend=prices[0])
    gain = np.clip(diff, 0, None)
    loss = -np.clip(diff, None, 0)
    ru = pd.Series(gain).rolling(period).mean()
    rd = pd.Series(loss).rolling(period).mean()
    rs = ru / (rd + 1e-9)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50).values

def _stoch(h, l, c, k=14, d=3) -> Tuple[np.ndarray, np.ndarray]:
    df = pd.DataFrame({"h": h, "l": l, "c": c})
    ll = df.l.rolling(k).min(); hh = df.h.rolling(k).max()
    kv = 100 * (df.c - ll) / (hh - ll + 1e-9)
    dv = kv.rolling(d).mean()
    return kv.fillna(50).values, dv.fillna(50).values

def build_price_features(candles: List[Dict[str, Any]]) -> Dict[str, float]:
    if not candles:
        return {}
    close = np.array([c["close"] for c in candles], float)
    high  = np.array([c.get("high", c["close"]) for c in candles], float)
    low   = np.array([c.get("low",  c["close"]) for c in candles], float)
    feats = {
        "ema9":  float(_ema(close, 9)[-1]),
        "ema20": float(_ema(close, 20)[-1]),
        "rsi14": float(_rsi(close, 14)[-1]),
    }
    k, d = _stoch(high, low, close)
    feats.update({"stoch_k": float(k[-1]), "stoch_d": float(d[-1])})
    return feats

def adapt_chain_features(chain_json: Dict[str, Any]) -> Dict[str, float]:
    if not chain_json:
        return {}

    def flatten(m):
        out = []
        for _exp, strikes in (m or {}).items():
            for _strike, arr in strikes.items():
                out.extend(arr)
        return out

    def collect(legs):
        ivs, deltas, gammas = [], [], []
        for leg in legs:
            g = (leg or {}).get("greeks", {})
            ivs.append(g.get("iv")); deltas.append(g.get("delta")); gammas.append(g.get("gamma"))
        filt = lambda xs: np.array([x for x in xs if x is not None], float)
        return filt(ivs), filt(deltas), filt(gammas)

    call_legs = flatten(chain_json.get("callExpDateMap"))
    put_legs  = flatten(chain_json.get("putExpDateMap"))

    civ, cdel, cgam = collect(call_legs)
    piv, pdel, pgam = collect(put_legs)

    feats = {}
    if civ.size: feats["call_iv_mean"] = float(np.nanmean(civ))
    if cdel.size:
        feats["call_delta_mean"] = float(np.nanmean(cdel))
        feats["call_delta_abs_mean"] = float(np.nanmean(np.abs(cdel)))
    if cgam.size: feats["call_gamma_mean"] = float(np.nanmean(cgam))

    if piv.size: feats["put_iv_mean"] = float(np.nanmean(piv))
    if pdel.size:
        feats["put_delta_mean"] = float(np.nanmean(pdel))
        feats["put_delta_abs_mean"] = float(np.nanmean(np.abs(pdel)))
    if pgam.size: feats["put_gamma_mean"] = float(np.nanmean(pgam))

    return feats

# ========= Public hook for your AI engine =========
def fetch_features(uid: str, symbol: str, *, period="1D", interval="1m",
                   chain_kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    c = SchwabClient(uid)
    candles = c.price_history(symbol, period=period, interval=interval).get("candles") or []
    price_feats = build_price_features(candles)
    chain_raw   = c.option_chains(symbol, **(chain_kwargs or {}))
    chain_feats = adapt_chain_features(chain_raw)
    return {**price_feats, **chain_feats}

# ========= Flask Blueprint =========
api = Blueprint("schwab_api", __name__, url_prefix="/api/schwab")

def _admin_ok() -> bool:
    return request.headers.get("X-Admin-Token") == cfg("ADMIN_API_TOKEN", "change-me")

def _uid() -> str:
    # If you have a real session, adapt this to read session user id
    return request.headers.get("X-User-Id", "demo-user")

@api.get("/auth/login")
def auth_login():
    return jsonify(SchwabClient(_uid()).login_url())

@api.get("/auth/callback")
def auth_callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        return jsonify({"error": "missing code/state"}), 400
    uid = read_state(state)["uid"]
    SchwabClient(uid).exchange_code(code, state)
    return redirect("/linked")

@api.post("/quotes")
def quotes():
    if not _admin_ok():
        return jsonify({"error": "unauthorized"}), 401
    symbols = (request.get_json(force=True) or {}).get("symbols", [])
    return jsonify(SchwabClient(_uid()).quotes(symbols))

@api.post("/pricehistory")
def pricehistory():
    if not _admin_ok():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True) or {}
    return jsonify(SchwabClient(_uid()).price_history(
        data["symbol"], data.get("period", "1D"), data.get("interval", "1m")
    ))

@api.post("/chains")
def chains():
    if not _admin_ok():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True) or {}
    sym = data.pop("symbol")
    return jsonify(SchwabClient(_uid()).option_chains(sym, **data))

@api.get("/accounts")
def accounts():
    if not _admin_ok():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(SchwabClient(_uid()).accounts())

@api.get("/positions/<account_id>")
def positions(account_id: str):
    if not _admin_ok():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(SchwabClient(_uid()).positions(account_id))

