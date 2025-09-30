# api/main.py
from __future__ import annotations
import os
from typing import Optional, Literal, List
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from .db import init_db

# 1) Create the app first
app = FastAPI(
    title="Koinonia",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 2) CORS (must use explicit origins when allow_credentials=True)
_default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"
allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3) Cookie→Authorization shim so old deps reading headers still work
class CookieToAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cookie_name: str = "access_token"):
        super().__init__(app)
        self.cookie_name = cookie_name
    async def dispatch(self, request, call_next):
        if not request.headers.get("authorization"):
            token = request.cookies.get(self.cookie_name)
            if token:
                headers = list(request.scope.get("headers", []))
                headers.append((b"authorization", f"Bearer {token}".encode()))
                request.scope["headers"] = headers
        return await call_next(request)

app.add_middleware(CookieToAuthMiddleware, cookie_name=os.getenv("COOKIE_NAME", "access_token"))

# 4) Lifecycle + health
@app.on_event("startup")
def _startup():
    init_db()

@app.get("/healthz")
def healthz():
    return {"ok": True}

# 5) Routers (after app exists)
from .auth import router as auth_router
from .analytics import router as analytics_router
from .admin import router as admin_router
from .trade import router as trade_router

app.include_router(auth_router)
app.include_router(analytics_router)
app.include_router(admin_router)
app.include_router(trade_router)

# 6) Mount Flask under /flask (after app exists)
from starlette.middleware.wsgi import WSGIMiddleware
from legacy_flask.app import create_app as create_flask_app
app.mount("/flask", WSGIMiddleware(create_flask_app()))

# 7) Suggestions endpoint
from engine.suggest import suggest_for_symbol

class Greek(BaseModel):
    delta: float | None = None
    theta: float | None = None
    vega: float | None = None

class Leg(BaseModel):
    type: str
    action: str
    strike: float | None = None
    expiry: str | None = None
    qty: int | None = None
    mid: float | None = None
    greeks: Greek | None = None

class SuggestionResponse(BaseModel):
    ticker: str | None = None
    strategy: str | None = None
    legs: List[Leg] | None = None
    debit: float | None = None
    max_profit: float | None = None
    risk_reward: float | None = None
    entry_rule: str | None = None
    exits: dict | None = None
    sizing: dict | None = None
    context: dict | None = None
    skip: str | None = None
    note: str | None = None
    error: str | None = None

@app.get("/suggestions", response_model=SuggestionResponse)
def suggestions(
    symbol: str = Query(..., min_length=1),
    expiry: Optional[str] = Query(None, description="YYYY-MM-DD"),
    strike: Optional[float] = Query(None),
    bias: Optional[Literal["call", "put"]] = Query(None),
):
    return suggest_for_symbol(symbol, overrides={"expiry": expiry, "strike": strike, "bias": bias})
