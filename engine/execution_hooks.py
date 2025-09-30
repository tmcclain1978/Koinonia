from __future__ import annotations
from typing import Optional, Dict, Any
import time

try:
    from engine.order_router import OrderRouter, Mode, CircuitBreaker
    from utils.config import cfg
except Exception:
    OrderRouter = None
    Mode = None
    CircuitBreaker = Exception

# Single global router; server.py also initializes one, but this gives a fallback
_ROUTER = None
def _get_router():
    global _ROUTER
    if _ROUTER is not None:
        return _ROUTER
    try:
        from engine.order_router import OrderRouter, RiskLimits, Mode
        from utils.config import cfg
        _ROUTER = OrderRouter(
            mode=(Mode.DEMO if cfg.paper_mode else Mode.LIVE),
            risk=RiskLimits(
                max_orders_per_hour=cfg.risk.max_orders_per_hour,
                max_daily_loss=cfg.risk.max_daily_loss,
                max_position=cfg.risk.max_position,
            ),
        )
    except Exception:
        _ROUTER = None
    return _ROUTER

def place_order_v2(mode: str, side: str, stake: float, symbol: str, idemp_key: Optional[str] = None) -> Dict[str, Any]:
    """Unified order entry guarded by OrderRouter.
    - mode: 'demo' | 'live'
    - side: 'call' | 'put'
    """
    router = _get_router()
    if router is None:
        return {"ok": False, "error": "router_unavailable"}
    try:
        ok, reason = router.can_place(stake=stake, idemp_key=idemp_key)
        if not ok:
            return {"ok": False, "error": reason}

        # DEMO: simulate a fill with 0 PnL and return accepted
        if mode.lower() == "demo":
            router.mark_filled(pnl=0.0, idemp_key=idemp_key)
            return {
                "ok": True,
                "mode": "demo",
                "side": side,
                "symbol": symbol,
                "stake": stake,
                "ts": int(time.time() * 1000),
                "status": "accepted",
            }

        # LIVE: allow upstream caller to handle the actual broker action
        if mode.lower() == "live":
            # We don't execute here—just pass router guard; caller should do broker action
            return {
                "ok": True,
                "mode": "live",
                "side": side,
                "symbol": symbol,
                "stake": stake,
                "ts": int(time.time() * 1000),
                "status": "guard_passed",
            }

        return {"ok": False, "error": "unknown_mode"}
    except CircuitBreaker as e:
        return {"ok": False, "error": f"circuit_breaker:{e}"}
    except Exception as e:
        return {"ok": False, "error": f"unexpected:{e}"}


def mark_live_filled(pnl: float, idemp_key: Optional[str] = None) -> bool:
    router = _get_router()
    if router is None:
        return False
    try:
        router.mark_filled(pnl=float(pnl or 0.0), idemp_key=idemp_key)
        return True
    except Exception:
        return False
