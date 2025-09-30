# auth_dao.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
AUTH_DB  = BASE_DIR / "auth.db"

def _auth_db():
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_auth_schema():
    conn = _auth_db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username       TEXT UNIQUE NOT NULL,
            email          TEXT UNIQUE,
            pw_hash        TEXT NOT NULL,
            role           TEXT NOT NULL DEFAULT 'user',
            can_use_ai     INTEGER NOT NULL DEFAULT 1,
            can_trade_bot  INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL
        );
        """)
        # backfill columns if running against an older db
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "can_use_ai" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN can_use_ai INTEGER NOT NULL DEFAULT 1")
        if "can_trade_bot" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN can_trade_bot INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    finally:
        conn.close()

def user_find_by_id(user_id: str):
    conn = _auth_db()
    try:
        return conn.execute(
            "SELECT id, username, email, pw_hash, role, can_use_ai, can_trade_bot, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

def user_find_by_username(username: str):
    conn = _auth_db()
    try:
        return conn.execute(
            "SELECT id, username, email, pw_hash, role, can_use_ai, can_trade_bot, created_at FROM users WHERE username = ?",
            (username,)
        ).fetchone()
    finally:
        conn.close()

def user_find_by_email(email: str):
    conn = _auth_db()
    try:
        return conn.execute(
            "SELECT id, username, email, pw_hash, role, can_use_ai, can_trade_bot, created_at FROM users WHERE email = ?",
            (email,)
        ).fetchone()
    finally:
        conn.close()

def user_create(username: str, email: str | None, password: str,
                role: str = "user", can_use_ai: bool = True, can_trade_bot: bool = False):
    conn = _auth_db()
    try:
        conn.execute(
            "INSERT INTO users(username, email, pw_hash, role, can_use_ai, can_trade_bot, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                username,
                (email or None),
                generate_password_hash(password),
                role,
                1 if can_use_ai else 0,
                1 if can_trade_bot else 0,
                datetime.utcnow().isoformat()
            )
        )
        conn.commit()
    finally:
        conn.close()
