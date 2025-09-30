# ai/options_ai_bot.py
from __future__ import annotations
import os, math
from typing import Any, Dict, Optional, Tuple

from ai import AIEngine                      # our built-in engine
from integrations.schwab_adapter import SchwabClient, fetch_features

Number = float

class OptionsAIBot:
    """
    Maps PocketOptions-like signals OR in-house features to normalized option orders.
    Produces the same schema your /api/trade/preview|submit expects.

    Typical usage:
        bot = OptionsAIBot(user_id)
        order = bot.propose(symbol="AAPL", signal={"type":"CALL","confidence":0.7})
        # or: order = bot.propose(symbol="AAPL")  # uses AIEngine on features
    """

    def __init__(self, user_id: str, *, model_path: Optional[str] = None, config: Optional[dict] = None):
        self.user_id = user_id or "user"
        self.client = SchwabClient(self.user_id)
        self.engine = AIEngine(model_path or os.getenv("AI_MODEL_PATH"))
        # sensible defaults; override via config
        self.cfg = {
            "qty": 1,              # contracts
            "dte": 7,              # target days to expiration
            "delta_target": 0.35,  # aim for ~35Δ long options (fallback to ATM)
            "order_type": "LIMIT", # entry type for non-bracket/oco
            "duration": "DAY",
            "session": "NORMAL",
            "bracket": {           # profit target / stop as option-premium limits
                "use": False,
                "target_rr": 1.0,  # target premium = debit * (1 + target_rr)
                "stop_rr": 0.5     # stop premium = debit * (1 - stop_rr)
            },
        }
        if config:
            # shallow update is fine; nested dict (bracket) can be overridden by providing full dict
            self.cfg.update(config)

    # ---------- public API ----------

    def propose(self, *, symbol: str, signal: Optional[Dict[str, Any]] = None,
                period: str = "5D", interval: str = "1m") -> Dict[str, Any]:
        """
        If `signal` provided ({"type":"CALL|PUT|HOLD", "confidence":0..1}), map it.
        Otherwise compute features and call AIEngine, then map to an order.
        Returns a normalized order dict suitable for /api/trade/preview|submit.
        """
        side: Optional[str] = None
        conf: float = 0.5

        if signal:  # explicit external signal
            st = (signal.get("type") or "").upper()
            if st == "HOLD" or not st:
                return self._hold_order(symbol)
            if st in ("CALL", "PUT"):
                side, conf = st, float(signal.get("confidence", 0.5))
            else:
                # unknown signal -> fall back to engine
                side, conf = self._engine_side(symbol, period, interval)
        else:
            side, conf = self._engine_side(symbol, period, interval)
            if side is None:
                return self._hold_order(symbol)

        # choose expiration/strike around target Δ (or ATM)
        exp, strike, mid = self._choose_contract(symbol, side, dte=self.cfg["dte"], delta_target=self.cfg["delta_target"])

        # choose order type (bracket if enabled)
        if self.cfg["bracket"]["use"]:
            debit = mid if mid is not None else 0.50
            target = round(debit * (1 + float(self.cfg["bracket"]["target_rr"])), 2)
            stop_p = round(max(0.05, debit * (1 - float(self.cfg["bracket"]["stop_rr"]))), 2)
            return {
                "account_id": None,             # UI fills or user selects for live
                "symbol": symbol,
                "orderType": "BRACKET",         # implemented as OTOCO on server
                "session": self.cfg["session"],
                "duration": self.cfg["duration"],
                "strategy": "SINGLE",
                "quantity": int(self.cfg["qty"]),
                "price": round(debit, 2),
                "legs": [{
                    "asset": "OPTION", "action": "BUY", "side": side,
                    "strike": strike, "expiration": exp, "quantity": int(self.cfg["qty"])
                }],
                "attached": { "target": target, "stop": stop_p }
            }

        # plain single-leg entry (MARKET/LIMIT/STOP/STOP_LIMIT are decided by UI or cfg)
        limit_px = round(mid, 2) if mid is not None else None
        order_type = self.cfg["order_type"].upper()
        payload: Dict[str, Any] = {
            "account_id": None,
            "symbol": symbol,
            "orderType": order_type,
            "session": self.cfg["session"],
            "duration": self.cfg["duration"],
            "strategy": "SINGLE",
            "quantity": int(self.cfg["qty"]),
            "legs": [{
                "asset": "OPTION", "action": "BUY", "side": side,
                "strike": strike, "expiration": exp, "quantity": int(self.cfg["qty"])
            }]
        }
        if order_type in ("LIMIT", "STOP_LIMIT") and limit_px is not None:
            payload["price"] = float(limit_px)
        return payload

    # ---------- internals ----------

    def _engine_side(self, symbol: str, period: str, interval: str) -> Tuple[Optional[str], float]:
        """Compute features and ask AIEngine for side (CALL/PUT) or HOLD."""
        feats = fetch_features(self.user_id, symbol, period=period, interval=interval)
        spot = self._spot(symbol)
        act = self.engine.propose(symbol=symbol, features=feats, spot=spot)
        if act.get("type") == "SINGLE":
            return act.get("side"), float(act.get("confidence", 0.5))
        return None, float(act.get("confidence", 0.5))

    def _spot(self, symbol: str) -> Optional[Number]:
        try:
            q = self.client.quotes([symbol])
            k = list(q.keys())[0]
            return float(q[k].get("quote",{}).get("lastPrice") or q[k].get("lastPrice"))
        except Exception:
            return None

    def _choose_contract(self, symbol: str, side: str, *, dte: int, delta_target: float
                         ) -> Tuple[str, float, Optional[Number]]:
        """
        Pick expiration closest to `dte` and strike near target Δ (fallback to ATM).
        Returns (YYYY-MM-DD, strike, mid) where mid is the option's mid price.
        """
        chains = self.client.chains(symbol)
        exp_key, exp_date = self._best_expiration(chains, dte)
        strike, mid = self._best_strike(chains, exp_key, side, delta_target, spot=self._spot(symbol))
        return exp_date, strike, mid

    def _best_expiration(self, chains: Dict[str, Any], dte: int) -> Tuple[str, str]:
        # expiration keys look like "YYYY-MM-DD:0" or "YYYY-MM-DD"
        import datetime as dt
        def _parse(key: str) -> dt.date:
            d = key.split(":")[0]
            y,m,day = d.split("-")
            return dt.date(int(y), int(m), int(day))
        today = dt.date.today()
        # try calls map; if empty, use puts map
        maps = chains.get("callExpDateMap") or chains.get("putExpDateMap") or {}
        if not maps:
            raise RuntimeError("No expirations in chain map.")
        # choose the date with min |(exp - today).days - dte|
        best = min(maps.keys(), key=lambda k: abs((_parse(k) - today).days - dte))
        return best, best.split(":")[0]

    def _best_strike(self, chains: Dict[str, Any], exp_key: str, side: str, delta_target: float,
                     *, spot: Optional[Number]) -> Tuple[float, Optional[Number]]:
        # Get list for the expiration & side; structure is {strike: [contract_dict, ...]}
        m = chains["callExpDateMap" if side == "CALL" else "putExpDateMap"]
        legs = m.get(exp_key) or m.get(exp_key.split(":")[0]) or {}
        # choose by |delta - target|; fallback to ATM (min |strike-spot|)
        best_k, best_mid, best_score = None, None, float("inf")
        for k, arr in legs.items():
            try:
                c = arr[0]
                delta = abs(float(c.get("delta", 0.0)))
                bid = float(c.get("bid", 0) or 0)
                ask = float(c.get("ask", 0) or 0)
                mid = (bid + ask)/2 if (bid>0 and ask>0) else None
                score = abs(delta - delta_target) if delta else 999
                if score < best_score:
                    best_k, best_mid, best_score = float(k), mid, score
            except Exception:
                continue
        if best_k is not None:
            return best_k, best_mid
        # fallback: ATM
        if spot is None:
            spot = 0.0
        ks = sorted([float(x) for x in legs.keys()]) if legs else [round(float(spot or 0.0))]
        atm = min(ks, key=lambda K: abs(K - (spot or ks[0])))
        # try to recover mid for ATM
        mid = None
        try:
            arr = legs.get(str(int(atm))) or next(iter(legs.values()))
            c = arr[0]
            bid = float(c.get("bid", 0) or 0); ask = float(c.get("ask", 0) or 0)
            mid = (bid + ask)/2 if (bid>0 and ask>0) else None
        except Exception:
            pass
        return float(atm), mid

    def _hold_order(self, symbol: str) -> Dict[str, Any]:
        return {
            "account_id": None,
            "symbol": symbol,
            "orderType": "MARKET",
            "session": self.cfg["session"],
            "duration": self.cfg["duration"],
            "strategy": "SINGLE",
            "quantity": 0,
            "legs": [],
            "note": "HOLD signal — no trade"
        }
