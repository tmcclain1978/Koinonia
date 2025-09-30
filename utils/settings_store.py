from __future__ import annotations
import os, json
from dataclasses import dataclass
from typing import Optional

_JSON_PATH = os.getenv("RISK_JSON_PATH", "config/risk.json")
_DB_URL = os.getenv("DATABASE_URL")

@dataclass
class RiskCaps:
    max_orders_per_hour: int = 30
    max_daily_loss: float = 0.0
    max_position: float = 0.0

def _load_json() -> Optional[RiskCaps]:
    try:
        if not os.path.exists(_JSON_PATH):
            return None
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return RiskCaps(
            max_orders_per_hour=int(d.get("max_orders_per_hour", 30)),
            max_daily_loss=float(d.get("max_daily_loss", 0.0)),
            max_position=float(d.get("max_position", 0.0)),
        )
    except Exception:
        return None

def _save_json(caps: RiskCaps) -> None:
    os.makedirs(os.path.dirname(_JSON_PATH), exist_ok=True)
    with open(_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "max_orders_per_hour": caps.max_orders_per_hour,
            "max_daily_loss": caps.max_daily_loss,
            "max_position": caps.max_position
        }, f)

def get_caps() -> RiskCaps:
    # Try DB first if available
    try:
        if _DB_URL:
            from sqlalchemy import create_engine, text
            eng = create_engine(_DB_URL, future=True)
            with eng.begin() as con:
                con.execute(text("CREATE TABLE IF NOT EXISTS Settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
                row = con.execute(text("SELECT value FROM Settings WHERE key='risk_caps'")).fetchone()
                if row and row[0]:
                    d = json.loads(row[0])
                    return RiskCaps(
                        max_orders_per_hour=int(d.get("max_orders_per_hour", 30)),
                        max_daily_loss=float(d.get("max_daily_loss", 0.0)),
                        max_position=float(d.get("max_position", 0.0)),
                    )
    except Exception:
        pass
    # Fallback to JSON file
    jc = _load_json()
    return jc or RiskCaps()

def set_caps(caps: RiskCaps) -> None:
    saved_db = False
    try:
        if _DB_URL:
            from sqlalchemy import create_engine, text
            eng = create_engine(_DB_URL, future=True)
            with eng.begin() as con:
                con.execute(text("CREATE TABLE IF NOT EXISTS Settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
                con.execute(text("INSERT INTO Settings (key, value) VALUES ('risk_caps', :v) ON CONFLICT(key) DO UPDATE SET value=:v"),
                            {"v": json.dumps({
                                "max_orders_per_hour": caps.max_orders_per_hour,
                                "max_daily_loss": caps.max_daily_loss,
                                "max_position": caps.max_position
                            })})
                saved_db = True
    except Exception:
        saved_db = False
    # Always write JSON too as a secondary fallback
    _save_json(caps)
