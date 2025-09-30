import asyncio, pandas as pd
from typing import List, Dict, Any
from adapters import polygon_async as poly
from adapters import tradier_async as trad
from adapters import schwab_async as schwab
from features.compute_features_live import build_features

def tv_link(symbol: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={symbol.upper()}"

async def pick_contract(symbol: str, bullish: bool) -> str:
    exps = None  # Schwab chain returns expirations embedded; we scan by days to expiry from option_chain
    if not exps: return f"{symbol} (no chain)"
    today = pd.Timestamp.utcnow().tz_localize(None).date()
    target=None
    for e in exps:
        try:
            d=pd.to_datetime(e).date()
            if 3 <= (d - today).days <= 7: target=e; break
        except Exception: continue
    if target is None: target=exps[0]
    ch = await schwab.option_chain(symbol, contractType='ALL', includeQuotes=True, strikeCount=200)
    if not ch: return f"{symbol} {target} (no greeks)"
    opts = []
    # Schwab returns 'callExpDateMap' and 'putExpDateMap'
    def collect(map_obj, side):
        if not isinstance(map_obj, dict): return
        for exp, strikes in map_obj.items():
            for k, arr in strikes.items():
                for o in arr:
                    o['option_type'] = side
                    opts.append(o)
    collect(ch.get('callExpDateMap'), 'call')
    collect(ch.get('putExpDateMap'), 'put')
    if not isinstance(opts, list) or not opts: return f"{symbol} {target} (empty chain)"
    desired=[]
    for o in opts:
        delta = o.get('delta') or o.get('totalDelta')
        try: d=float(delta) if delta is not None else None
        except: d=None
        if d is None: continue
        if bullish and o.get('option_type')=='call' and 0.45<=d<=0.65: desired.append(o)
        if (not bullish) and o.get('option_type')=='put' and -0.65<=d<=-0.45: desired.append(o)
    if not desired: desired=opts[:10]
    def score(o):
        bid=float(o.get('bid') or o.get('bidPrice') or 0 or 0); ask=float(o.get('ask') or o.get('askPrice') or 0 or 0); oi=int(o.get('openInterest',0) or 0)
        spr=(ask-bid) if (ask and bid and ask>bid) else 1e9
        return (spr, -oi)
    desired.sort(key=score)
    return desired[0].get('symbol')

async def pick_vertical(symbol: str, bullish: bool) -> str:
    exps = None  # Schwab chain returns expirations embedded; we scan by days to expiry from option_chain
    if not exps: return f"{symbol} (no chain)"
    today = pd.Timestamp.utcnow().tz_localize(None).date()
    target=None
    for e in exps:
        try:
            d=pd.to_datetime(e).date()
            if 3 <= (d - today).days <= 7: target=e; break
        except Exception: continue
    if target is None: target=exps[0]
    ch = await schwab.option_chain(symbol, contractType='ALL', includeQuotes=True, strikeCount=200)
    if not ch: return f"{symbol} {target} (no greeks)"
    opts = []
    # Schwab returns 'callExpDateMap' and 'putExpDateMap'
    def collect(map_obj, side):
        if not isinstance(map_obj, dict): return
        for exp, strikes in map_obj.items():
            for k, arr in strikes.items():
                for o in arr:
                    o['option_type'] = side
                    opts.append(o)
    collect(ch.get('callExpDateMap'), 'call')
    collect(ch.get('putExpDateMap'), 'put')
    calls=[o for o in opts if o.get('option_type')=='call']
    puts =[o for o in opts if o.get('option_type')=='put']
    side_list = calls if bullish else puts
    if not side_list: return f"{symbol} {target} (no side chain)"
    target_delta = 0.55 if bullish else -0.55
    def dd(o):
        try: return abs(float(o.get('greeks',{}).get('delta',0)) - target_delta)
        except: return 9e9
    side_list.sort(key=dd)
    long_leg = side_list[0]
    def strike(o):
        try: return float(o.get('strikePrice',0))
        except: return 0.0
    lk = strike(long_leg)
    cands=[o for o in side_list[1:] if 2.0 <= abs(strike(o)-lk) <= 5.0]
    if not cands: return long_leg.get('symbol')
    def score(o):
        bid=float(o.get('bid') or o.get('bidPrice') or 0 or 0); ask=float(o.get('ask') or o.get('askPrice') or 0 or 0); oi=int(o.get('openInterest',0) or 0)
        spr=(ask-bid) if (ask and bid and ask>bid) else 1e9
        return (spr, -oi)
    cands.sort(key=score)
    short_leg=cands[0]
    return f"{long_leg.get('symbol')} / {short_leg.get('symbol')}"

def _z(x): return 0.0 if x is None else x
def _tradable(f): return f.get('equity_adv',0) >= 5_000_000 and f.get('spread_score',0) >= 0.5

async def generate_picks_live(n:int=10) -> List[Dict[str,Any]]:
    universe = await poly.most_actives(limit=100)
    feats = await build_features(universe)
    out=[]
    for sym, f in feats.items():
        if not _tradable(f): continue
        long_iv_bonus = max(0.0, (0.4 - f.get('iv_percentile',0.5)))
        score = (0.25*_z(f.get('rs_20')) + 0.20*_z(f.get('ema_stack')) + 0.20*long_iv_bonus + 0.20*_z(f.get('flow_z')) + 0.15*_z(f.get('spread_score')))
        bullish = f.get('ema_stack',0)>0 and f.get('rs_20',0)>0
        contract = await pick_contract(sym, bullish)
        if f.get('iv_percentile',0.5) > 0.6:
            contract = await pick_vertical(sym, bullish)
        out.append({
            'symbol': sym,
            'strategy': 'debit_vertical' if f.get('iv_percentile',0.5) > 0.5 else 'long_option',
            'score': round(score,3),
            'rationale': [
                'Uptrend (stacked EMAs)' if f.get('ema_stack',0)>0 else 'Non-uptrend',
                'Positive 20d RS vs SPY' if f.get('rs_20',0)>0 else 'Weak RS',
                'Relatively cheap IV' if f.get('iv_percentile',0.5)<0.4 else 'IV not cheap',
                f"Flow z={round(f.get('flow_z',0.0),2)}"
            ],
            'suggested_contract': contract,
            'stop_plan': 'premium_stop_35pct_or_time_14:30ET',
            'sizing_hint': 'risk ≤ 0.5R',
            'risk_policy': {
                'max_daily_loss_R': 1.0,
                'max_open_risk_R': 1.5,
                'friday_size_multiplier': 0.5,
                'stop_rules': ['premium_stop_35pct','time_stop_14:30ET']
            },
            'tv_url': tv_link(sym),
            **f
        })
    out.sort(key=lambda x: x['score'], reverse=True)
    return out[:n]
