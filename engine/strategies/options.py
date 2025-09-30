from typing import Dict, Any, List
import math

def pick_bull_call_spread(chain: List[Dict[str, Any]], spot: float, target_days=35, width=10) -> Dict[str, Any]:
    # naive selector: buy ~0.35Δ call, sell strike +width
    c = [o for o in chain if o["type"]=="CALL" and 15 <= o["dte"] <= 60]
    if not c: return {}
    c = sorted(c, key=lambda x: abs(x.get("delta",0.35)-0.35))
    buy = c[0]
    sell_strike = buy["strike"] + width
    opp = sorted([o for o in c if o["strike"]==sell_strike and o["expiry"]==buy["expiry"]], key=lambda x: -x.get("delta",0))
    if not opp: return {}
    sell = opp[0]
    debit = round(buy["mid"] - sell["mid"], 2)
    max_profit = round(width - debit, 2)
    rr = max_profit/debit if debit>0 else 0
    return {"strategy":"bull_call_spread","legs":[
        {"type":"CALL","action":"BUY", **buy},
        {"type":"CALL","action":"SELL",**sell},
    ], "debit":debit,"max_profit":max_profit,"risk_reward":round(rr,2)}
