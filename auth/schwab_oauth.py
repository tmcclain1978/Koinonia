import os, time, requests
from urllib.parse import urlencode

AUTH_BASE   = os.getenv("SCHWAB_AUTH_BASE").rstrip("/")
TOKEN_URL   = f"{AUTH_BASE}/oauth/token"      # confirm path in your developer portal
AUTH_URL    = f"{AUTH_BASE}/authorize"        # confirm path in your developer portal
CLIENT_ID   = os.getenv("SCHWAB_CLIENT_ID")
CLIENT_SEC  = os.getenv("SCHWAB_CLIENT_SECRET")
REDIRECT    = os.getenv("SCHWAB_REDIRECT_URI")
SCOPES      = os.getenv("SCHWAB_SCOPES", "traderapi").split()

def build_login_url(state: str):
    q = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "scope": " ".join(SCOPES),
        "state": state
    }
    return f"{AUTH_URL}?{urlencode(q)}"

def _stamp(tok: dict) -> dict:
    tok["expires_at"] = int(time.time()) + int(tok.get("expires_in", 1800))
    return tok

def exchange_code_for_tokens(code: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SEC,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return _stamp(r.json())

def refresh_tokens(refresh_token: str) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SEC,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return _stamp(r.json())
