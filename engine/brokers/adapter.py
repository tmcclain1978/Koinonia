from __future__ import annotations
from typing import Dict, Any, Optional
from .base import BrokerAdapter, RetryPolicy, with_retries, TransientBrokerError, PermanentBrokerError

class PocketOptionAdapter:
    def place_order(self, side: str, stake: float, symbol: str, idempotency_key: Optional[str]) -> Dict[str, Any]:
        # TODO: Real Selenium click flow here
        # Simulate success
        return {
            "ok": True,
            "broker": "pocketoption",
            "status": "submitted",
            "side": side,
            "stake": stake,
            "symbol": symbol,
            "idempotency_key": idempotency_key
        }

class SchwabAdapter:
    def place_order(self, side: str, stake: float, symbol: str, idempotency_key: Optional[str]) -> Dict[str, Any]:
        # TODO: Real Schwab API call here; raise TransientBrokerError on 5xx/timeouts; PermanentBrokerError on 4xx
        return {
            "ok": True,
            "broker": "schwab",
            "status": "submitted",
            "side": side,
            "stake": stake,
            "symbol": symbol,
            "idempotency_key": idempotency_key
        }

def get_adapter(broker: str) -> BrokerAdapter:
    b = (broker or "").lower()
    if b in ("po","pocketoption","pocket_option"):
        return PocketOptionAdapter()
    if b in ("schwab","charles_schwab"):
        return SchwabAdapter()
    # default to pocket option for wiring, but mark error in result
    return PocketOptionAdapter()

def execute_live_order(broker: str, side: str, stake: float, symbol: str, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    adapter = get_adapter(broker)
    ok, res = with_retries(lambda: adapter.place_order(side, stake, symbol, idempotency_key), RetryPolicy())
    if ok and isinstance(res, dict):
        return res
    return {"ok": False, "error": res if isinstance(res, str) else "unknown_error"}
