from typing import Dict, Any
import pandas as pd
from .datasources.router import DataRouter
from .features.technical import make_feats
from .strategies.options import pick_bull_call_spread

from typing import Dict, Any
import pandas as pd
from .datasources.router import DataRouter
from .features.technical import make_feats

def suggest_for_symbol(symbol: str, overrides: dict | None = None) -> Dict[str, Any]:
    ds = DataRouter()

    # candles
    try:
        bars = ds.candles(symbol, "1d", 200)
    except Exception as e:
        return {"error":"market_data_error","detail":f"candles: {str(e)[:200]}", "ticker": symbol.upper()}
    df = pd.DataFrame(bars)
    if df.empty:
        return {"error":"no_data","detail":"no candles returned", "ticker": symbol.upper()}

    feats = make_feats(df)
    spot = float(df.iloc[-1]["close"])

    # options chain
    try:
        chain = ds.options_chain(symbol)
    except Exception as e:
        return {"error":"market_data_error","detail":f"options_chain: {str(e)[:200]}", "ticker": symbol.upper()}
    if not chain:
        return {"error":"no_data","detail":"empty options chain", "ticker": symbol.upper()}

    # (… keep your override/default strategy logic …)
    return {"note":"stub strategy; plug in your logic", "ticker": symbol.upper(), "context":{"spot":spot,"iv_rank":float(feats.get("iv_rank",0))}}

    # --- override-aware path ---
    expiry = (overrides or {}).get("expiry")
    strike = (overrides or {}).get("strike")
    bias   = (overrides or {}).get("bias")  # "call" | "put" | None

    if expiry and strike and bias:
        # pick nearest contract from chain
        def pick(side):
            # chain rows should include: type ("call"/"put"), expiry, strike, bid, ask, mid
            rows = [r for r in chain if str(r.get("expiry")) == str(expiry)
                    and float(r.get("strike", 0)) == float(strike)
                    and r.get("type") == side]
            if not rows: return None
            r = sorted(rows, key=lambda x: abs((x.get("bid",0)+x.get("ask",0))/2 - x.get("mid",0) or 0))[0]
            mid = r.get("mid") or ( (r.get("bid") or 0) + (r.get("ask") or 0) )/2
            return {"type": side, "action": "buy", "strike": strike, "expiry": expiry, "qty": 1, "mid": float(mid)}

        leg = pick(bias)
        if leg:
            debit = leg["mid"]
            return {
                "ticker": symbol.upper(),
                "strategy": f"long_{bias}",
                "legs": [leg],
                "debit": float(debit),
                "max_profit": None,   # theoretically large for long options
                "risk_reward": None,
                "entry_rule": f"Buy 1 {bias.upper()} {strike} exp {expiry} at <= mid",
                "exits": {"stop_loss_pct": 50, "take_profit_pct": 100, "time_exit_days": 3},
                "sizing": {"risk_usd": 300, "contracts": 1},
                "context": {"spot": spot, "iv_rank": float(feats.get('iv_rank', 0))},
            }

    # --- default path (your existing strategy selection) ---
    # ... keep your current heuristic here ...
    return {"note":"no override matched; plug in your default strategy logic", "ticker": symbol.upper()}
