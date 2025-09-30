import os
from dataclasses import dataclass
from typing import Optional
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

def _get_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None: return default
    return v.strip().lower() in ("1","true","yes","on")

def _get_float(name: str, default: float) -> float:
    v = os.getenv(name)
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

@dataclass
class RiskConfig:
    max_orders_per_hour: int = int(os.getenv("MAX_ORDERS_PER_HOUR", "30"))
    max_daily_loss: float = _get_float("MAX_DAILY_LOSS", 0.0)
    max_position: float = _get_float("MAX_POSITION", 0.0)

@dataclass
class AppConfig:
    enable_trading: bool = _get_bool("ENABLE_TRADING", False)
    paper_mode: bool = _get_bool("PAPER_MODE", True)
    log_level: str = os.getenv("LOG_LEVEL","INFO")
    risk: RiskConfig = RiskConfig()

cfg = AppConfig()
