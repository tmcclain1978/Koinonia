# api/auth.py
from __future__ import annotations
import os, secrets, datetime as dt
from typing import Callable, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, status, Header, Response, Request
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import User

router = APIRouter(prefix="/auth", tags=["auth"])

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
JWT_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"
JWT_TTL_MIN = int(os.getenv("JWT_TTL_MIN", "720"))

COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrf_token")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")  # Lax | Strict | None
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None     # e.g. ".koinonia.app" in prod

REGISTRATION_CODE = os.getenv("REGISTRATION_CODE")
ADMIN_API_TOKEN  = os.getenv("ADMIN_API_TOKEN", "")

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: Literal["user", "admin"] = "user"

class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    invite_code: Optional[str] = None

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class MeOut(BaseModel):
    id: int
    email: EmailStr
    role: Literal["user","admin"]
    trade_enabled: bool
    can_trade_paper: bool
    can_trade_live: bool

# -----------------------------------------------------------------------------
# DB session dep
# -----------------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------------------------------------------------------
# JWT helpers
# -----------------------------------------------------------------------------
def create_jwt(user: User) -> str:
    now = dt.datetime.utcnow()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=JWT_TTL_MIN)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])

def _set_login_cookies(resp: Response, token: str):
    # HttpOnly token cookie
    resp.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, domain=COOKIE_DOMAIN, path="/"
    )
    # Non-HttpOnly CSRF cookie (double-submit)
    csrf = secrets.token_urlsafe(24)
    resp.set_cookie(
        key=CSRF_COOKIE_NAME, value=csrf, httponly=False, secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE, domain=COOKIE_DOMAIN, path="/"
    )

def _clear_cookies(resp: Response):
    for name in (COOKIE_NAME, CSRF_COOKIE_NAME):
        resp.delete_cookie(key=name, domain=COOKIE_DOMAIN, path="/")

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    if REGISTRATION_CODE and body.invite_code not in (REGISTRATION_CODE, ADMIN_API_TOKEN):
        raise HTTPException(status_code=403, detail="Registration code invalid")

    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = "admin" if (body.invite_code and body.invite_code == ADMIN_API_TOKEN) else "user"
    user = User(email=body.email.lower(), password_hash=bcrypt.hash(body.password), role=role)
    db.add(user); db.commit(); db.refresh(user)

    token = create_jwt(user)
    _set_login_cookies(response, token)
    return TokenOut(access_token=token, role=user.role)

@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not bcrypt.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")

    token = create_jwt(user)
    _set_login_cookies(response, token)
    return TokenOut(access_token=token, role=user.role)

@router.post("/logout")
def logout(response: Response):
    _clear_cookies(response)
    return {"ok": True}

@router.get("/me", response_model=MeOut)
def me(user: "User" = Depends(lambda authorization=Header(None), db=Depends(get_db): current_user(authorization, db))):
    return MeOut(
        id=user.id, email=user.email, role=user.role,
        trade_enabled=user.trade_enabled, can_trade_paper=user.can_trade_paper, can_trade_live=user.can_trade_live
    )

# -----------------------------------------------------------------------------
# Auth deps (reads header *or* cookie)
# -----------------------------------------------------------------------------
def current_user(authorization: Optional[str], db: Session) -> User:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    # Fallback to cookie (when called from FastAPI routes)
    # We'll pull cookie from Request if available via dependency injection
    # In this signature we don't have Request, so consumers pass via wrapper above.
    try:
        payload = decode_jwt(token) if token else None
    except JWTError:
        payload = None
    # If no Authorization header, try request state (middleware approach avoided for simplicity)
    if payload is None:
        # This variant fetches token via Starlette request when available
        # We'll inject via a wrapper in routes needing auth
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = int(payload.get("sub", 0))
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    return user

# Helper that actually reads cookies when available (for FastAPI routes)
from fastapi import Cookie
def current_user_cookie(
    request: Request,
    db: Session = Depends(get_db),
    token_cookie: Optional[str] = Cookie(default=None, alias=COOKIE_NAME)
) -> User:
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
    elif token_cookie:
        token = token_cookie
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        payload = decode_jwt(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, int(payload.get("sub", 0)))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    return user

# Role gate (uses cookie-aware dep)
def require_role(required: Literal["admin","user"]) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user_cookie)) -> User:
        if required == "admin" and user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin required")
        return user
    return dep
