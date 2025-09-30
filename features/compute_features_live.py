import asyncio, math, numpy as np, pandas as pd
from typing import Dict, Any, List, Optional
from adapters import polygon_async as poly
from adapters import schwab_async as schwab
from adapters import tradier_async as trad
from adapters import unusualwhales_async as uw
from utils import iv_cache

def ema(series: List[float], span: int) -> float:
    if not series or len(series) < span: return float('nan')
    return pd.Series(series).ewm(span=span, adjust=False).mean().iloc[-1]

def compute_ema_stack(prices: List[float]) -> float:
    if len(prices) < 60: return 0.0
    e9, e20, e50 = ema(prices,9), ema(prices,20), ema(prices,50)
    if pd.isna(e9) or pd.isna(e20) or pd.isna(e50): return 0.0
    return 1.0 if e9>e20>e50 else (-1.0 if e9<e20<e50 else 0.0)

def rel_strength_20(sym_hist: List[float], spy_hist: List[float]) -> float:
    if len(sym_hist) < 21 or len(spy_hist) < 21: return 0.0
    return (sym_hist[-1]/sym_hist[-21]-1.0) - (spy_hist[-1]/spy_hist[-21]-1.0)

def spread_score_from_snap(bid: Optional[float], ask: Optional[float]) -> float:
    if not bid or not ask or ask<=0 or bid<=0: return 0.0
    mid=(bid+ask)/2.0
    if mid<=0: return 0.0
    bps=(ask-bid)/mid*10000.0
    if bps<=15: return 1.0
    if bps>=40: return 0.0
    return max(0.0, min(1.0, 1-(bps-15)/25.0))

def iv_percentile_proxy(chain: dict) -> float:
    try:
        options = chain.get('options', {}).get('option', [])
        if not isinstance(options, list) or len(options) < 10: return 0.5
        ivs=[]; 
        for opt in options:
            g=opt.get('greeks',{}); iv=g.get('mid_iv') or g.get('iv'); delta=g.get('delta')
            if iv is None or delta is None: continue
            if abs(abs(float(delta)) - 0.5) < 0.15: ivs.append(float(iv))
        if not ivs: return 0.5
        curr=float(np.median(ivs))
        pct=sum(1 for x in ivs if x<=curr)/len(ivs)
        return float(pct)
    except Exception: return 0.5

def zscore_last(values: List[float]) -> float:
    if not values or len(values) < 10: return 0.0
    s=pd.Series(values[-20:]); 
    return 0.0 if s.std()==0 else float((s.iloc[-1]-s.mean())/s.std())

async def build_features(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    iv_cache.init()
    try:
        # Try Schwab quotes first
        quotes = await schwab.quotes(symbols)
        snaps = {}
        if quotes:
            # Map Schwab quote fields -> bid/ask/volume
            # Schwab returns dict keyed by symbol
            for sym, q in quotes.items():
                try:
                    b = q.get('bidPrice') or q.get('quote',{}).get('bidPrice')
                    a = q.get('askPrice') or q.get('quote',{}).get('askPrice')
                    v = q.get('totalVolume') or q.get('quote',{}).get('totalVolume')
                    snaps[sym] = {'bid':b, 'ask':a, 'volume':v}
                except Exception:
                    pass
        else:
            snaps = await poly.snapshots(symbols)
    except Exception:
        snaps = await poly.snapshots(symbols)
    spy_hist=[]
    try:
        ph = await schwab.price_history('SPY','year',1,'daily',1)
        if ph and ph.get('candles'):
            spy_hist = [c.get('close') for c in ph['candles']][-60:]
    except Exception:
        spy_aggs = await poly.aggregates('SPY','day',60)
        spy_hist=[b.get('c') for b in (spy_aggs or []) if 'c' in b]

    async def sym_hist(sym):
        ph = await schwab.price_history(sym,'year',1,'daily',1)
        if ph and ph.get('candles'):
            closes = [c.get('close') for c in ph['candles']][-60:]
        else:
            ag = await poly.aggregates(sym,'day',60)
            closes = [b.get('c') for b in (ag or []) if 'c' in b]
        return sym, closes
    hists={}
    tasks=[sym_hist(s) for s in symbols]
    for coro in asyncio.as_completed(tasks):
        sym, prices = await coro; hists[sym]=prices

    flow_map={}
    for s in symbols:
        flow_map[s] = await uw.flow_series(s, 20)

    async def ivp_for_symbol(sym:str)->float:
        exps = await trad.expirations(sym)
        if not exps: return 0.5
        today = pd.Timestamp.utcnow().tz_localize(None).date()
        target=None
        for e in exps[:10]:
            try:
                d=pd.to_datetime(e).date(); dd=(d-today).days
                if 3<=dd<=7: target=e; break
            except Exception: continue
        if target is None: target=exps[0]
        ch=await trad.chain(sym, target, greeks=True)
        if not ch: return 0.5
        # derive current ATM-ish IV
        options=ch.get('options',{}).get('option',[])
        ivs=[]; 
        for o in options:
            g=o.get('greeks',{}); iv=g.get('mid_iv') or g.get('iv'); delta=g.get('delta')
            try:
                if iv is None or delta is None: continue
                if abs(abs(float(delta))-0.5)<0.15: ivs.append(float(iv))
            except Exception: 
                continue
        curr_iv = float(np.median(ivs)) if ivs else 0.0
        if curr_iv<=0: return 0.5
        # update cache and compute percentile on history
        asof = str(today)
        ivp = iv_cache.upsert_and_percentile(sym, asof, curr_iv, lookback_days=252)
        return float(ivp)

    ivp_map={}
    for s in symbols:
        ivp_map[s] = await ivp_for_symbol(s)

    feats={}
    for s in symbols:
        snap=snaps.get(s,{}); closes=hists.get(s,[])
        ema_stack=compute_ema_stack(closes)
        rs20=rel_strength_20(closes, spy_hist) if closes and spy_hist else 0.0
        sc=spread_score_from_snap(snap.get('bid'), snap.get('ask'))
        fz=zscore_last(flow_map.get(s) or [])
        ivp=ivp_map.get(s,0.5)
        feats[s]={'symbol':s,'ema_stack':ema_stack,'rs_20':rs20,'equity_adv':snap.get('volume') or 0,'spread_score':sc,'iv_percentile':ivp,'flow_z':fz}
    return feats
