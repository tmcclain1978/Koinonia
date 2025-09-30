import pandas as pd
from typing import Dict, Any, List
from adapters import polygon_adapter as poly

def ema(vals: List[float], span:int):
    if len(vals)<span: return float('nan')
    return pd.Series(vals).ewm(span=span, adjust=False).mean().iloc[-1]

def compute_ema_stack(closes: List[float])->float:
    if len(closes)<60: return 0.0
    e9,e20,e50=ema(closes,9),ema(closes,20),ema(closes,50)
    if pd.isna(e9) or pd.isna(e20) or pd.isna(e50): return 0.0
    return 1.0 if e9>e20>e50 else (-1.0 if e9<e20<e50 else 0.0)

def rs20(sym: List[float], spy: List[float])->float:
    if len(sym)<21 or len(spy)<21: return 0.0
    return (sym[-1]/sym[-21]-1)-(spy[-1]/spy[-21]-1)

def spread_score(bid,ask)->float:
    if not bid or not ask: return 0.0
    mid=(bid+ask)/2.0
    if not mid: return 0.0
    bps=(ask-bid)/mid*10000.0
    if bps<=15: return 1.0
    if bps>=40: return 0.0
    return max(0.0, min(1.0, 1-(bps-15)/25.0))

def fetch_closes(sym:str, n:int=60)->List[float]:
    ag=poly.get_aggregates(sym,'day',limit=n)
    if not ag: return []
    return [a.get('c') for a in ag if 'c' in a][-n:]

def build_features(symbols: List[str])->Dict[str,Dict[str,Any]]:
    snaps=poly.get_snapshot(symbols); spy_hist=fetch_closes('SPY',60)
    feats={}
    for s in symbols:
        close=fetch_closes(s,60)
        e=compute_ema_stack(close)
        r=rs20(close, spy_hist) if close and spy_hist else 0.0
        snap=snaps.get(s,{}) if isinstance(snaps,dict) else {}
        sc=spread_score(snap.get('bid'), snap.get('ask'))
        feats[s]={ 'symbol':s,'ema_stack':e,'rs_20':r,'equity_adv':snap.get('volume') or 0,'spread_score':sc,'iv_percentile':0.5,'flow_z':0.0 }
    return feats
